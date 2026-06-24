"""
agent.py
--------
Fully agentic AWS query engine. There is no fixed tool list — every user
query is answered by generating a fresh, read-only Boto3 function with an
LLM, statically validating it for safety, executing it in a sandboxed
thread with a timeout, and then summarizing the raw result back into a
natural-language reply.

Flow:
    generate_code()  -> validate_code()  -> execute_code()  -> summarize_result()
                              |
                       (reject if unsafe)

Public entry point used by main.py:
    run_agent_query(query, region, access_key, secret_key, groq_caller) -> dict
        Always returns a dict with at least a "reply" key (string, safe to
        display directly in chat) plus either "result" (success) or
        "error" (failure) for logging/debugging.
"""

import ast
import json
import logging
import threading
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ── Configuration ─────────────────────────────────────────────────────────────
MAX_RETRIES     = 2          # how many times the agent may try to fix its own code
EXEC_TIMEOUT_S  = 25         # hard wall-clock limit per execution attempt

# Only these modules may be imported by generated code
ALLOWED_IMPORTS = {"boto3", "json", "datetime", "botocore"}

# Only read-only boto3 method name *prefixes* are allowed
ALLOWED_CALL_PREFIXES = ("describe_", "get_", "list_", "head_")

# These builtins are exposed to generated code — nothing else
ALLOWED_BUILTINS = {
    "len": len, "range": range, "str": str, "int": int, "float": float,
    "bool": bool, "list": list, "dict": dict, "set": set, "tuple": tuple,
    "sorted": sorted, "round": round, "min": min, "max": max, "sum": sum,
    "enumerate": enumerate, "zip": zip, "isinstance": isinstance,
    "type": type, "repr": repr, "format": format, "abs": abs,
    "any": any, "all": all, "filter": filter, "map": map, "reversed": reversed,
    "True": True, "False": False, "None": None,
    # __import__ must be present for the `import boto3` statement inside the
    # generated code to work at all — the AST validator (validate_code) is
    # what actually restricts *which* modules can be imported, not this.
    "__import__": __import__,
    # Exception types — needed since generated code is instructed to wrap
    # AWS calls in try/except blocks (per the codegen prompt).
    "Exception": Exception, "ValueError": ValueError, "KeyError": KeyError,
    "TypeError": TypeError, "IndexError": IndexError, "AttributeError": AttributeError,
    "StopIteration": StopIteration, "RuntimeError": RuntimeError,
}

# Names that must NEVER appear in generated code, anywhere
FORBIDDEN_NAMES = {
    "os", "sys", "subprocess", "socket", "shutil", "pathlib",
    "eval", "exec", "compile", "__import__", "open", "input",
    "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "exit", "quit", "help",
}

# Boto3 / botocore call prefixes that mutate or destroy infrastructure —
# blocked even if they don't match the forbidden-name list above.
FORBIDDEN_CALL_PREFIXES = (
    "delete_", "terminate_", "modify_", "create_", "put_", "update_",
    "start_", "stop_", "reboot_", "run_", "attach_", "detach_",
    "authorize_", "revoke_", "associate_", "disassociate_", "reset_",
    "register_", "deregister_", "purchase_", "cancel_", "release_",
    "import_", "copy_", "restore_", "enable_", "disable_",
)


class CodeSafetyError(Exception):
    """Raised when generated code fails the AST safety check."""
    pass


class CodeExecutionError(Exception):
    """Raised when generated code raises an exception or times out."""
    pass


# ── Phase 0: Intent classification ────────────────────────────────────────────
def classify_intent(query: str, groq_caller) -> str:
    """
    Classifies the user's query into one of three buckets before any Boto3
    code is generated:

    - "data"      : asks about the user's actual AWS resources/state
                    (e.g. "show running instances", "tell me about my EC2 fleet")
    - "conceptual": asks what an AWS service/term/concept IS, generally
                    (e.g. "what is EC2", "explain security groups")
    - "off_topic" : not about AWS at all (e.g. "what's the weather")

    Returns one of: "data", "conceptual", "off_topic"
    """
    system = (
        "Classify the user's message into exactly one category. Reply with "
        "ONLY one word, lowercase, no punctuation: data, conceptual, or off_topic.\n\n"
        "- data: the user wants information about THEIR OWN AWS account/resources "
        "(e.g. 'show running instances', 'list my buckets', 'tell me about my EC2 fleet', "
        "'what's the CPU usage', 'how many volumes do I have').\n"
        "- conceptual: the user is asking what an AWS service or term IS in general, "
        "not asking about their own resources (e.g. 'what is EC2', 'what is a security group', "
        "'explain how S3 works', 'difference between EBS and S3').\n"
        "- off_topic: not related to AWS at all (e.g. weather, sports, math, general chit-chat).\n\n"
        "When ambiguous, prefer 'data' if the query could plausibly be answered by looking at "
        "the user's actual resources."
    )
    try:
        response = groq_caller(
            [{"role": "system", "content": system}, {"role": "user", "content": query}],
            tools=None,
        )
        label = (response.choices[0].message.content or "").strip().lower()
        if label not in ("data", "conceptual", "off_topic"):
            return "data"  # safest default: fall through to the real pipeline
        return label
    except Exception as e:
        logger.warning(f"[agent] Intent classification failed, defaulting to 'data': {e}")
        return "data"


def answer_conceptual_question(query: str, groq_caller) -> str:
    """
    Answers a general AWS knowledge question directly — no Boto3, no AWS
    credentials touched. Used for questions like "what is EC2".
    """
    system = (
        "You are an AWS infrastructure assistant. The user asked a general "
        "conceptual question about AWS (not about their own account/resources). "
        "Answer clearly and concisely in 2-4 sentences. If relevant, briefly "
        "mention you can also look up their actual resources if they ask "
        "(e.g. 'show my running instances')."
    )
    try:
        response = groq_caller(
            [{"role": "system", "content": system}, {"role": "user", "content": query}],
            tools=None,
        )
        text = response.choices[0].message.content
        return text.strip() if text else "I'm not able to answer that right now."
    except Exception as e:
        logger.warning(f"[agent] Conceptual answer generation failed: {e}")
        return "I'm not able to answer that right now."


# ── Phase 4: Result summarization ─────────────────────────────────────────────
def build_summary_prompt(query: str, result) -> list:
    """
    Builds the message list asking the LLM to turn raw AWS JSON into a clear,
    human-readable chat reply. This replaces the old tool-calling loop's
    natural final-answer step now that there's no fixed-tool LLM round-trip.
    """
    result_json = json.dumps(result, default=str)[:8000]  # cap size sent back to LLM
    system = (
        "You are an AWS infrastructure assistant. You were given a user's query "
        "and the raw JSON result of an AWS Boto3 call made to answer it. "
        "Write a clear, concise, human-readable answer using ONLY the data given. "
        "Never invent IDs, IPs, names, or values not present in the JSON. "
        "If the JSON contains an 'error' key, explain the error plainly to the user. "
        "If a list is empty, say so in plain natural language matching the user's own "
        "wording — e.g. for a query about EC2 instances with no results, say "
        "\"You don't have any EC2 instances in this region\" rather than a generic "
        "phrase like 'the list is empty'. Use short bullet points for multiple items."
    )
    user_content = f"User query: {query}\n\nRaw result JSON:\n{result_json}"
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def summarize_result(query: str, result, groq_caller) -> str:
    """Turns the raw dict/list result into a natural-language chat reply."""
    try:
        messages = build_summary_prompt(query, result)
        response = groq_caller(messages, tools=None)
        text = response.choices[0].message.content
        return text.strip() if text else json.dumps(result, default=str)
    except Exception as e:
        logger.warning(f"[agent] Summary generation failed, falling back to raw JSON: {e}")
        return json.dumps(result, default=str, indent=2)


# ── Phase 1: Code generation ──────────────────────────────────────────────────
def build_codegen_prompt(query: str, region: str, previous_error: str = None, previous_code: str = None) -> list:
    """Builds the message list sent to the LLM to generate Boto3 code."""
    system = f"""You are an expert AWS Boto3 code generator. You write exactly ONE Python function
named `run` that answers the user's AWS query using read-only Boto3 calls.

The user's query has already been confirmed to be a legitimate request about their own
AWS resources (EC2 instances, CloudWatch metrics, S3 buckets, RDS, Lambda, IAM, VPCs,
security groups, EBS volumes, load balancers, Route53, SNS, SQS, ECS, EKS, etc).

STRICT RULES:
- Define exactly one function: def run(region, access_key, secret_key):
- Only import: boto3, json, datetime (no other imports, no "import os" etc.)
- Only call read-only boto3 methods: describe_*, get_*, list_*, head_*
- NEVER use AI/ML services like comprehend, rekognition, translate, polly to answer questions
- NEVER call delete_*, terminate_*, modify_*, create_*, put_*, update_*, start_*, stop_*, or any mutating action
- Build boto3 clients like: boto3.client("ec2", region_name=region, aws_access_key_id=access_key, aws_secret_access_key=secret_key)
- Return a JSON-serializable dict or list. Convert datetimes to .isoformat() strings.
- Wrap AWS calls in try/except and return {{"error": "..."}} on failure — never let exceptions escape.
- No file access, no subprocess, no network calls outside boto3, no eval/exec.
- Return ONLY the Python code. No markdown fences, no explanation, no comments before/after the function.

The current AWS region context is: {region}
"""
    user_content = f"User query: {query}\n\nWrite the `run` function to answer this."

    if previous_error and previous_code:
        user_content = (
            f"User query: {query}\n\n"
            f"Your previous code failed with this error:\n{previous_error}\n\n"
            f"Previous code:\n{previous_code}\n\n"
            f"Fix the code and return the corrected `run` function only."
        )

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]


def extract_code(raw_text: str) -> str:
    """Strips markdown fences if the LLM added them despite instructions."""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def generate_code(query: str, region: str, groq_caller, previous_error: str = None, previous_code: str = None) -> str:
    """
    Calls the LLM (via groq_caller — main.py's call_llm_with_tools-style function)
    to produce Boto3 code. groq_caller must accept (messages, tools=None) and
    return an object with .choices[0].message.content
    """
    messages = build_codegen_prompt(query, region, previous_error, previous_code)
    response = groq_caller(messages, tools=None)
    raw = response.choices[0].message.content or ""
    return extract_code(raw)


# ── Phase 2: AST-based safety validation ──────────────────────────────────────
def validate_code(code: str) -> None:
    """
    Raises CodeSafetyError if the code violates any safety rule.
    Returns None (passes) otherwise.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise CodeSafetyError(f"Generated code has a syntax error: {e}")

    found_run_function = False

    for node in ast.walk(tree):

        # Block disallowed imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_mod = alias.name.split(".")[0]
                if root_mod not in ALLOWED_IMPORTS:
                    raise CodeSafetyError(f"Disallowed import: '{alias.name}'")

        if isinstance(node, ast.ImportFrom):
            root_mod = (node.module or "").split(".")[0]
            if root_mod not in ALLOWED_IMPORTS:
                raise CodeSafetyError(f"Disallowed import: 'from {node.module}'")

        # Block forbidden names anywhere (os, eval, exec, open, subprocess, ...)
        if isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
            raise CodeSafetyError(f"Use of forbidden name: '{node.id}'")

        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_NAMES:
            raise CodeSafetyError(f"Use of forbidden attribute: '.{node.attr}'")

        # Block mutating boto3/botocore method calls by name prefix
        if isinstance(node, ast.Attribute):
            method_name = node.attr
            if method_name.startswith(FORBIDDEN_CALL_PREFIXES):
                raise CodeSafetyError(
                    f"Mutating/destructive AWS call blocked: '.{method_name}(...)'. "
                    "Only read-only calls (describe_*, get_*, list_*, head_*) are permitted."
                )

        # Detect the run() function definition
        if isinstance(node, ast.FunctionDef) and node.name == "run":
            found_run_function = True
            arg_names = [a.arg for a in node.args.args]
            if arg_names[:3] != ["region", "access_key", "secret_key"]:
                raise CodeSafetyError(
                    "Function 'run' must have signature: run(region, access_key, secret_key)"
                )

    if not found_run_function:
        raise CodeSafetyError("No function named 'run' was found in the generated code.")


# ── Phase 3: Sandboxed execution with timeout ─────────────────────────────────
def execute_code(code: str, region: str, access_key: str, secret_key: str) -> dict:
    """
    Executes validated code in a restricted namespace with a hard timeout.
    Raises CodeExecutionError on failure or timeout.
    """
    import boto3
    import botocore  # needed so generated code can catch botocore.exceptions

    safe_globals = {
        "__builtins__": ALLOWED_BUILTINS,
        "boto3": boto3,
        "botocore": botocore,   # ← allows: from botocore.exceptions import ClientError
        "json": json,
        "datetime": datetime,
        "timedelta": timedelta,
    }
    safe_locals = {}

    result_container = {"value": None, "error": None}

    def _run():
        try:
            exec(code, safe_globals, safe_locals)
            run_fn = safe_locals.get("run") or safe_globals.get("run")
            if run_fn is None:
                result_container["error"] = "No 'run' function found after exec."
                return
            result_container["value"] = run_fn(region, access_key, secret_key)
        except Exception as e:
            result_container["error"] = f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=EXEC_TIMEOUT_S)

    if thread.is_alive():
        raise CodeExecutionError(f"Execution timed out after {EXEC_TIMEOUT_S}s.")

    if result_container["error"]:
        raise CodeExecutionError(result_container["error"])

    # Ensure the result is JSON-serializable; fall back to str() for stray objects
    try:
        json.dumps(result_container["value"])
    except (TypeError, ValueError):
        result_container["value"] = json.loads(json.dumps(result_container["value"], default=str))

    return result_container["value"]


# ── Public entry point ────────────────────────────────────────────────────────
def run_agent_query(query: str, region: str, access_key: str, secret_key: str, groq_caller) -> dict:
    """
    Full agentic loop: generate -> validate -> execute, with retry-on-error.

    groq_caller: a callable(messages, tools=None) -> response object with
                 .choices[0].message.content, matching main.py's call_llm_with_tools
                 signature (pass tools=None for plain text generation).

    Returns a dict always containing at least:
        { "agent_used": True, "result": <data> }
    or on unrecoverable failure:
        { "agent_used": True, "error": "<message>", "code": "<last code tried>" }
    """
    last_error = None
    last_code = None

    # ── Phase 0: classify intent before touching AWS or generating any code ───
    intent = classify_intent(query, groq_caller)
    logger.info(f"[agent] Query classified as: {intent!r}")

    if intent == "off_topic":
        return {
            "agent_used": True,
            "reply": "I can only answer questions about AWS — your infrastructure, "
                     "or general AWS concepts. Try asking something like "
                     "'show my running instances' or 'what is an EBS volume'.",
            "intent": "off_topic",
        }

    if intent == "conceptual":
        reply = answer_conceptual_question(query, groq_caller)
        return {
            "agent_used": True,
            "reply": reply,
            "intent": "conceptual",
        }

    # intent == "data" — proceed with the normal generate -> validate -> execute pipeline
    for attempt in range(MAX_RETRIES + 1):
        try:
            code = generate_code(
                query, region, groq_caller,
                previous_error=last_error, previous_code=last_code,
            )
            last_code = code

            validate_code(code)
            logger.info(f"[agent] Code passed validation on attempt {attempt + 1}")

            result = execute_code(code, region, access_key, secret_key)
            logger.info(f"[agent] Execution succeeded on attempt {attempt + 1}")

            reply = summarize_result(query, result, groq_caller)

            return {
                "agent_used": True,
                "reply": reply,
                "result": result,
                "generated_code": code,
                "intent": "data",
            }

        except CodeSafetyError as e:
            logger.warning(f"[agent] Safety validation failed (attempt {attempt + 1}): {e}")
            return {
                "agent_used": True,
                "reply": f"I can't run that query — it was rejected for safety reasons: {e}",
                "error": str(e),
                "code": last_code,
            }

        except CodeExecutionError as e:
            logger.warning(f"[agent] Execution failed (attempt {attempt + 1}): {e}")
            last_error = str(e)
            continue  # retry with the error fed back to the LLM

        except Exception as e:
            logger.error(f"[agent] Unexpected agent failure: {e}")
            last_error = str(e)
            continue

    return {
        "agent_used": True,
        "reply": f"I couldn't complete that query after {MAX_RETRIES + 1} attempts. Last error: {last_error}",
        "error": f"Agent failed after {MAX_RETRIES + 1} attempts. Last error: {last_error}",
        "code": last_code,
    }