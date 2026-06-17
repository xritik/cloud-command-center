"""
AWS Infrastructure Query Platform - FastAPI Backend
----------------------------------------------------
Connects Groq LLaMA 3 (tool use) with real AWS Boto3 calls.
Run: uvicorn main:app --reload --port 8000
"""

import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional

# ── Third-party imports ───────────────────────────────────────────────────────
import bcrypt
import boto3
from cryptography.fernet import Fernet
from botocore.exceptions import ClientError, NoCredentialsError
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from groq import Groq
from jose import JWTError, jwt
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── App setup ─────────────────────────────────────────────────────────────────
app = FastAPI(title="AWS Query Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── AWS clients ───────────────────────────────────────────────────────────────
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

def get_ec2(region=None, access_key=None, secret_key=None):
    return boto3.client(
        "ec2",
        region_name=region or os.getenv("AWS_REGION", "ap-south-1"),
        aws_access_key_id=access_key or os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=secret_key or os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

def get_cw(region=None, access_key=None, secret_key=None):
    return boto3.client(
        "cloudwatch",
        region_name=region or os.getenv("AWS_REGION", "ap-south-1"),
        aws_access_key_id=access_key or os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=secret_key or os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

# ── Groq API keys ────────────────────────────────────────────────────────────
# Add as many keys as you want in .env:
#   GROQ_KEY_1=gsk_...
#   GROQ_KEY_2=gsk_...
GROQ_KEYS = [
    v for k, v in sorted(os.environ.items())
    if k.startswith("GROQ_KEY_") and v.strip()
]
if not GROQ_KEYS and os.getenv("GROQ_API_KEY"):
    GROQ_KEYS = [os.getenv("GROQ_API_KEY")]

logger.info(f"Groq keys loaded: {len(GROQ_KEYS)}")

# ── MongoDB Atlas ─────────────────────────────────────────────────────────────
MONGO_URI    = os.getenv("MONGO_URI")
JWT_SECRET   = os.getenv("JWT_SECRET", "change-this-secret-in-production")
JWT_ALGO     = "HS256"
JWT_EXPIRE_H = 24

_mongo       = MongoClient(MONGO_URI) if MONGO_URI else None
db           = _mongo["cloudCommansCenter"] if _mongo is not None else None
users_col    = db["users"] if db is not None else None

accounts_col = db["aws_accounts"] if db is not None else None

if users_col is not None:
    users_col.create_index("username", unique=True)
if accounts_col is not None:
    accounts_col.create_index([("username", 1), ("label", 1)])

# Encryption for AWS credentials stored in Atlas
ENCRYPT_KEY = os.getenv("ENCRYPT_KEY", Fernet.generate_key().decode())
fernet = Fernet(ENCRYPT_KEY.encode() if isinstance(ENCRYPT_KEY, str) else ENCRYPT_KEY)

def encrypt_val(val: str) -> str:
    return fernet.encrypt(val.encode()).decode()

def decrypt_val(val: str) -> str:
    return fernet.decrypt(val.encode()).decode()

bearer_scheme = HTTPBearer()

# ── Auth helpers ──────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())

def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_H),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)) -> str:
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expired or invalid")

# ── Pydantic models ───────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    message: str
    history: list = []
    region: str = "ap-south-1"
    account_id: str = ""
    access_key: str = ""
    secret_key: str = ""

class AuthRequest(BaseModel):
    username: str
    password: str

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

class ChangeUsernameRequest(BaseModel):
    new_username: str
    current_password: str

class AWSAccountRequest(BaseModel):
    label: str
    access_key: str
    secret_key: str
    region: str = "ap-south-1"
    account_id: str = ""

class UpdateAWSAccountRequest(BaseModel):
    label: str = ""
    access_key: str = ""
    secret_key: str = ""
    region: str = ""

class DirectToolRequest(BaseModel):
    tool: str
    args: dict = {}
    region: str = "ap-south-1"
    access_key: str = ""
    secret_key: str = ""

# ── Tool definitions for Groq ─────────────────────────────────────────────────
AWS_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "list_instances",
            "description": "List all EC2 instances. Optionally filter by state: running, stopped, pending, terminated.",
            "parameters": {
                "type": "object",
                "properties": {
                    "state": {
                        "type": "string",
                        "enum": ["running", "stopped", "pending", "terminated", "all"],
                        "description": "Filter by instance state. Omit or use 'all' to list all."
                    }
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_instance_by_name",
            "description": "Get full details of an EC2 instance by its Name tag. Returns IPs, state, type, AZ.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "The Name tag of the EC2 instance, e.g. 'Lab1'"}
                },
                "required": ["name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_cpu_metrics",
            "description": "Get average CPU utilization % for a specific EC2 instance over the last N hours.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "EC2 instance ID, e.g. i-0abc1234567890def"},
                    "hours": {"type": "number", "description": "Hours back to query. Default 1."}
                },
                "required": ["instance_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_high_cpu_instances",
            "description": "List all running EC2 instances where average CPU usage exceeds a given threshold.",
            "parameters": {
                "type": "object",
                "properties": {
                    "threshold": {"type": "number", "description": "CPU % threshold, e.g. 70 means above 70%."}
                },
                "required": ["threshold"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_instance_status",
            "description": "Get system and instance health/status checks for a specific EC2 instance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "EC2 instance ID"}
                },
                "required": ["instance_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_security_groups",
            "description": "List all security groups, or security groups attached to a specific instance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "Optional EC2 instance ID to filter."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_volumes",
            "description": "List EBS volumes, optionally filtered by instance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "Optional EC2 instance ID to filter volumes."}
                }
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_memory_metrics",
            "description": "Get memory usage % for an EC2 instance. Requires CloudWatch agent on the instance.",
            "parameters": {
                "type": "object",
                "properties": {
                    "instance_id": {"type": "string", "description": "EC2 instance ID"},
                    "hours": {"type": "number", "description": "Hours back to query. Default 1."}
                },
                "required": ["instance_id"]
            }
        }
    }
]

# ── AWS helper ────────────────────────────────────────────────────────────────
def parse_instance(inst: dict) -> dict:
    tags = {t["Key"]: t["Value"] for t in inst.get("Tags", [])}
    return {
        "id": inst["InstanceId"],
        "name": tags.get("Name", "Unnamed"),
        "state": inst["State"]["Name"],
        "type": inst["InstanceType"],
        "public_ip": inst.get("PublicIpAddress", "N/A"),
        "private_ip": inst.get("PrivateIpAddress", "N/A"),
        "az": inst.get("Placement", {}).get("AvailabilityZone", "N/A"),
        "launch_time": inst["LaunchTime"].isoformat() if inst.get("LaunchTime") else "N/A",
        "image_id": inst.get("ImageId", "N/A"),
        "key_name": inst.get("KeyName", "N/A"),
        "vpc_id": inst.get("VpcId", "N/A"),
        "subnet_id": inst.get("SubnetId", "N/A"),
        "security_groups": [{"id": sg["GroupId"], "name": sg["GroupName"]} for sg in inst.get("SecurityGroups", [])],
        "tags": tags,
    }

# ── Tool implementations ──────────────────────────────────────────────────────
def list_instances(state: Optional[str] = None, region=None, access_key=None, secret_key=None) -> dict:
    try:
        ec2 = get_ec2(region, access_key, secret_key)
        filters = []
        if state and state != "all":
            filters.append({"Name": "instance-state-name", "Values": [state]})
        resp = ec2.describe_instances(Filters=filters)
        instances = [parse_instance(i) for r in resp["Reservations"] for i in r["Instances"]]
        return {"instances": instances, "count": len(instances)}
    except NoCredentialsError:
        raise HTTPException(401, "AWS credentials not configured. Check .env file.")
    except ClientError as e:
        raise HTTPException(500, f"AWS Error: {e.response['Error']['Message']}")


def get_instance_by_name(name: str, region=None, access_key=None, secret_key=None) -> dict:
    try:
        ec2 = get_ec2(region, access_key, secret_key)
        resp = ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": [name]}])
        for r in resp["Reservations"]:
            for inst in r["Instances"]:
                return {"found": True, "instance": parse_instance(inst)}
        return {"found": False, "message": f"No instance with Name tag '{name}' found."}
    except ClientError as e:
        raise HTTPException(500, f"AWS Error: {e.response['Error']['Message']}")


def get_cpu_metrics(instance_id: str, hours: float = 1, region=None, access_key=None, secret_key=None) -> dict:
    try:
        cw = get_cw(region, access_key, secret_key)
        end = datetime.utcnow()
        start = end - timedelta(hours=hours)
        resp = cw.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start, EndTime=end,
            Period=int(hours * 3600),
            Statistics=["Average", "Maximum", "Minimum"],
        )
        datapoints = sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
        if not datapoints:
            return {"instance_id": instance_id, "cpu_avg": None,
                    "message": "No data. Instance may be stopped or metrics unavailable."}
        latest = datapoints[-1]
        return {
            "instance_id": instance_id,
            "cpu_avg": round(latest.get("Average", 0), 2),
            "cpu_max": round(latest.get("Maximum", 0), 2),
            "cpu_min": round(latest.get("Minimum", 0), 2),
            "period_hours": hours,
            "timestamp": latest["Timestamp"].isoformat(),
        }
    except ClientError as e:
        raise HTTPException(500, f"AWS Error: {e.response['Error']['Message']}")


def list_high_cpu_instances(threshold: float = 70, region=None, access_key=None, secret_key=None) -> dict:
    all_data = list_instances(state="running", region=region, access_key=access_key, secret_key=secret_key)
    results = []
    for inst in all_data.get("instances", []):
        metrics = get_cpu_metrics(inst["id"], hours=1, region=region, access_key=access_key, secret_key=secret_key)
        cpu = metrics.get("cpu_avg")
        if cpu is not None and cpu >= threshold:
            results.append({**inst, "cpu_avg": cpu})
    return {"threshold": threshold, "instances": results, "count": len(results)}


def get_instance_status(instance_id: str, region=None, access_key=None, secret_key=None) -> dict:
    try:
        ec2 = get_ec2(region, access_key, secret_key)
        resp = ec2.describe_instance_status(InstanceIds=[instance_id], IncludeAllInstances=True)
        statuses = resp.get("InstanceStatuses", [])
        if not statuses:
            return {"instance_id": instance_id, "error": "Instance not found"}
        s = statuses[0]
        return {
            "instance_id": instance_id,
            "state": s["InstanceState"]["Name"],
            "instance_status": s["InstanceStatus"]["Status"],
            "system_status": s["SystemStatus"]["Status"],
            "instance_checks": [{"name": c["Name"], "status": c["Status"]}
                                 for c in s["InstanceStatus"].get("Details", [])],
            "system_checks": [{"name": c["Name"], "status": c["Status"]}
                               for c in s["SystemStatus"].get("Details", [])],
        }
    except ClientError as e:
        raise HTTPException(500, f"AWS Error: {e.response['Error']['Message']}")


def list_security_groups(instance_id: Optional[str] = None, region=None, access_key=None, secret_key=None) -> dict:
    try:
        ec2 = get_ec2(region, access_key, secret_key)
        if instance_id:
            resp = ec2.describe_instances(InstanceIds=[instance_id])
            sg_ids = [sg["GroupId"] for r in resp["Reservations"]
                      for inst in r["Instances"] for sg in inst.get("SecurityGroups", [])]
            if not sg_ids:
                return {"groups": [], "count": 0}
            sg_resp = ec2.describe_security_groups(GroupIds=sg_ids)
        else:
            sg_resp = ec2.describe_security_groups()
        groups = [{
            "id": sg["GroupId"], "name": sg["GroupName"],
            "description": sg["Description"], "vpc_id": sg.get("VpcId", "N/A"),
            "inbound_rules": len(sg.get("IpPermissions", [])),
            "outbound_rules": len(sg.get("IpPermissionsEgress", [])),
        } for sg in sg_resp["SecurityGroups"]]
        return {"groups": groups, "count": len(groups)}
    except ClientError as e:
        raise HTTPException(500, f"AWS Error: {e.response['Error']['Message']}")


def list_volumes(instance_id: Optional[str] = None, region=None, access_key=None, secret_key=None) -> dict:
    try:
        ec2 = get_ec2(region, access_key, secret_key)
        filters = [{"Name": "attachment.instance-id", "Values": [instance_id]}] if instance_id else []
        resp = ec2.describe_volumes(Filters=filters)
        volumes = []
        for vol in resp["Volumes"]:
            tags = {t["Key"]: t["Value"] for t in vol.get("Tags", [])}
            att = vol.get("Attachments", [])
            volumes.append({
                "id": vol["VolumeId"], "name": tags.get("Name", "Unnamed"),
                "size_gb": vol["Size"], "type": vol["VolumeType"],
                "state": vol["State"], "az": vol["AvailabilityZone"],
                "encrypted": vol.get("Encrypted", False), "iops": vol.get("Iops", "N/A"),
                "attached_to": att[0]["InstanceId"] if att else "Detached",
                "device": att[0]["Device"] if att else "N/A",
            })
        return {"volumes": volumes, "count": len(volumes)}
    except ClientError as e:
        raise HTTPException(500, f"AWS Error: {e.response['Error']['Message']}")


def get_memory_metrics(instance_id: str, hours: float = 1, region=None, access_key=None, secret_key=None) -> dict:
    try:
        cw = get_cw(region, access_key, secret_key)
        end = datetime.utcnow()
        start = end - timedelta(hours=hours)
        resp = cw.get_metric_statistics(
            Namespace="CWAgent", MetricName="mem_used_percent",
            Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
            StartTime=start, EndTime=end,
            Period=int(hours * 3600), Statistics=["Average"],
        )
        datapoints = sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
        if not datapoints:
            return {"instance_id": instance_id, "memory_avg": None,
                    "message": "No memory data. CloudWatch agent may not be installed."}
        return {
            "instance_id": instance_id,
            "memory_avg": round(datapoints[-1]["Average"], 2),
            "period_hours": hours,
        }
    except ClientError as e:
        raise HTTPException(500, f"AWS Error: {e.response['Error']['Message']}")


# ── Tool dispatcher ───────────────────────────────────────────────────────────
def run_tool(tool_name: str, args: dict, region: str = None, access_key: str = None, secret_key: str = None) -> dict:
    creds = dict(region=region, access_key=access_key, secret_key=secret_key)
    TOOL_MAP = {
        "list_instances":          lambda a: list_instances(a.get("state"), **creds),
        "get_instance_by_name":    lambda a: get_instance_by_name(a["name"], **creds),
        "get_cpu_metrics":         lambda a: get_cpu_metrics(a["instance_id"], a.get("hours", 1), **creds),
        "list_high_cpu_instances": lambda a: list_high_cpu_instances(a.get("threshold", 70), **creds),
        "get_instance_status":     lambda a: get_instance_status(a["instance_id"], **creds),
        "list_security_groups":    lambda a: list_security_groups(a.get("instance_id"), **creds),
        "list_volumes":            lambda a: list_volumes(a.get("instance_id"), **creds),
        "get_memory_metrics":      lambda a: get_memory_metrics(a["instance_id"], a.get("hours", 1), **creds),
    }
    if tool_name not in TOOL_MAP:
        return {"error": f"Unknown tool: {tool_name}"}
    logger.info(f"Tool: {tool_name} | Args: {args} | Region: {region}")
    return TOOL_MAP[tool_name](args)


# ── API Routes ────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "AWS Query Platform", "region": AWS_REGION}

@app.get("/regions")
def list_regions(username: str = Depends(get_current_user)):
    try:
        ec2 = boto3.client("ec2", region_name="us-east-1",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"))
        resp = ec2.describe_regions(AllRegions=False)
        regions = sorted([r["RegionName"] for r in resp["Regions"]])
        return {"regions": regions}
    except Exception:
        return {"regions": [
            "ap-south-1","ap-south-2","ap-southeast-1","ap-southeast-2",
            "ap-northeast-1","ap-northeast-2","ap-northeast-3",
            "us-east-1","us-east-2","us-west-1","us-west-2",
            "eu-west-1","eu-west-2","eu-west-3","eu-central-1",
            "ca-central-1","sa-east-1","af-south-1","me-south-1"
        ]}

@app.get("/health")
def health():
    try:
        sts = boto3.client(
            "sts",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
        identity = sts.get_caller_identity()
        return {
            "status": "healthy",
            "aws_connected": True,
            "account_id": identity["Account"],
            "user_arn": identity["Arn"],
            "region": AWS_REGION,
            "groq_key_set": bool(os.getenv("GROQ_API_KEY")),
        }
    except Exception as e:
        return {"status": "degraded", "aws_connected": False, "error": str(e)}


@app.post("/auth/signup")
def signup(req: AuthRequest):
    if users_col is None:
        raise HTTPException(500, "MongoDB not configured. Add MONGO_URI to .env")
    if len(req.username.strip()) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    if len(req.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    try:
        users_col.insert_one({
            "username":   req.username.strip().lower(),
            "password":   hash_password(req.password),
            "created_at": datetime.utcnow(),
        })
        token = create_token(req.username.strip().lower())
        return {"token": token, "username": req.username.strip().lower(), "message": "Account created successfully"}
    except DuplicateKeyError:
        raise HTTPException(400, "Username already exists. Please choose another.")


@app.post("/auth/login")
def login(req: AuthRequest):
    if users_col is None:
        raise HTTPException(500, "MongoDB not configured. Add MONGO_URI to .env")
    user = users_col.find_one({"username": req.username.strip().lower()})
    if not user or not verify_password(req.password, user["password"]):
        raise HTTPException(401, "Invalid username or password")
    token = create_token(user["username"])
    return {"token": token, "username": user["username"], "message": "Login successful"}


@app.get("/auth/me")
def me(username: str = Depends(get_current_user)):
    return {"username": username, "authenticated": True}


# ── Groq LLM caller with sticky key rotation ─────────────────────────────────
_groq_key_idx = 0  # remembers last working key across calls in the same session

def call_llm_with_tools(messages: list, tools: list) -> object:
    global _groq_key_idx
    if not GROQ_KEYS:
        raise HTTPException(503, "No Groq keys configured. Add GROQ_KEY_1 to your .env file.")

    for attempt in range(len(GROQ_KEYS)):
        idx = (_groq_key_idx + attempt) % len(GROQ_KEYS)
        key = GROQ_KEYS[idx]
        try:
            client = Groq(api_key=key)
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=tools,
                tool_choice="auto",
                parallel_tool_calls=False,
                temperature=0,
                max_tokens=4096,
            )
            _groq_key_idx = idx  # stick to this key for next call
            logger.info(f"✓ Groq key {idx + 1}/{len(GROQ_KEYS)} succeeded")
            return response
        except Exception as e:
            err_str = str(e).lower()
            if any(x in err_str for x in ["rate limit", "quota", "429"]):
                logger.warning(f"Groq key {idx + 1} rate-limited, trying next...")
                _groq_key_idx = (idx + 1) % len(GROQ_KEYS)
                continue
            # Dead/banned/invalid key — skip it, try next
            logger.warning(f"Groq key {idx + 1} skipped: {str(e)[:100]}")
            _groq_key_idx = (idx + 1) % len(GROQ_KEYS)
            continue

    raise HTTPException(429, "All Groq API keys are rate-limited. Add more keys or wait a minute.")


@app.post("/chat")
async def chat(req: ChatRequest, username: str = Depends(get_current_user)):
    system_msg = {
        "role": "system",
        "content": (
            f"You are an expert AWS Infrastructure Assistant for region {req.region}. "
            "Use the provided tools to fetch real AWS data. Never guess or fabricate details. "
            "After calling tools, summarize clearly and concisely. "
            "If an instance has no public IP, say so explicitly."
        )
    }
    messages = [system_msg] + req.history + [{"role": "user", "content": req.message}]
    tool_calls_log = []

    for _ in range(10):
        response = call_llm_with_tools(messages, AWS_TOOLS)
        assistant_msg = response.choices[0].message

        if not assistant_msg.tool_calls:
            return {
                "reply": assistant_msg.content,
                "tool_calls": tool_calls_log,
                "model": response.model,
                "usage": {
                    "prompt_tokens": response.usage.prompt_tokens,
                    "completion_tokens": response.usage.completion_tokens,
                }
            }

        messages.append({
            "role": "assistant",
            "content": assistant_msg.content,
            "tool_calls": [{
                "id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments}
            } for tc in assistant_msg.tool_calls]
        })

        for tc in assistant_msg.tool_calls:
            fn_name = tc.function.name
            fn_args = json.loads(tc.function.arguments or "{}")
            result = run_tool(fn_name, fn_args, region=req.region)
            tool_calls_log.append({"tool": fn_name, "args": fn_args, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

    return {"reply": "Reached max tool call limit.", "tool_calls": tool_calls_log}


@app.post("/tool")
def direct_tool(req: DirectToolRequest, username: str = Depends(get_current_user)):
    ak = req.access_key if req.access_key else os.getenv("AWS_ACCESS_KEY_ID")
    sk = req.secret_key if req.secret_key else os.getenv("AWS_SECRET_ACCESS_KEY")
    return run_tool(req.tool, req.args, region=req.region, access_key=ak, secret_key=sk)



# ── AWS Account routes ────────────────────────────────────────────────────────
@app.post("/accounts/add")
def add_account(req: AWSAccountRequest, username: str = Depends(get_current_user)):
    if accounts_col is None:
        raise HTTPException(500, "MongoDB not configured")
    # Test credentials before saving
    try:
        sts = boto3.client("sts",
            aws_access_key_id=req.access_key,
            aws_secret_access_key=req.secret_key)
        identity = sts.get_caller_identity()
        real_account_id = identity["Account"]
    except Exception as e:
        raise HTTPException(400, f"Invalid AWS credentials: {str(e)}")
    doc = {
        "username":   username,
        "label":      req.label,
        "access_key": encrypt_val(req.access_key),
        "secret_key": encrypt_val(req.secret_key),
        "region":     req.region,
        "account_id": real_account_id,
        "added_at":   datetime.utcnow(),
    }
    result = accounts_col.insert_one(doc)
    return {"message": "Account added successfully", "id": str(result.inserted_id), "account_id": real_account_id}


@app.get("/accounts")
def get_accounts(username: str = Depends(get_current_user)):
    if accounts_col is None:
        raise HTTPException(500, "MongoDB not configured")
    accounts = list(accounts_col.find({"username": username}, {"access_key": 0, "secret_key": 0}))
    for a in accounts:
        a["id"] = str(a.pop("_id"))
    return {"accounts": accounts, "count": len(accounts)}


@app.delete("/accounts/{account_id}")
def delete_account(account_id: str, username: str = Depends(get_current_user)):
    from bson import ObjectId
    if accounts_col is None:
        raise HTTPException(500, "MongoDB not configured")
    result = accounts_col.delete_one({"_id": ObjectId(account_id), "username": username})
    if result.deleted_count == 0:
        raise HTTPException(404, "Account not found")
    return {"message": "Account deleted"}


@app.put("/accounts/{account_id}")
def update_account(account_id: str, req: UpdateAWSAccountRequest, username: str = Depends(get_current_user)):
    from bson import ObjectId
    if accounts_col is None:
        raise HTTPException(500, "MongoDB not configured")
    updates = {}
    if req.label:      updates["label"]  = req.label
    if req.region:     updates["region"] = req.region
    if req.access_key: updates["access_key"] = encrypt_val(req.access_key)
    if req.secret_key: updates["secret_key"] = encrypt_val(req.secret_key)
    if not updates:
        raise HTTPException(400, "Nothing to update")
    accounts_col.update_one({"_id": ObjectId(account_id), "username": username}, {"$set": updates})
    return {"message": "Account updated"}


@app.post("/accounts/{account_id}/test")
def test_account(account_id: str, username: str = Depends(get_current_user)):
    from bson import ObjectId
    if accounts_col is None:
        raise HTTPException(500, "MongoDB not configured")
    acc = accounts_col.find_one({"_id": ObjectId(account_id), "username": username})
    if not acc:
        raise HTTPException(404, "Account not found")
    try:
        sts = boto3.client("sts",
            aws_access_key_id=decrypt_val(acc["access_key"]),
            aws_secret_access_key=decrypt_val(acc["secret_key"]))
        identity = sts.get_caller_identity()
        return {"valid": True, "account_id": identity["Account"], "arn": identity["Arn"]}
    except Exception as e:
        return {"valid": False, "error": str(e)}


# ── Profile routes ────────────────────────────────────────────────────────────
@app.put("/profile/password")
def change_password(req: ChangePasswordRequest, username: str = Depends(get_current_user)):
    if users_col is None:
        raise HTTPException(500, "MongoDB not configured")
    user = users_col.find_one({"username": username})
    if not user or not verify_password(req.current_password, user["password"]):
        raise HTTPException(401, "Current password is incorrect")
    if len(req.new_password) < 6:
        raise HTTPException(400, "New password must be at least 6 characters")
    users_col.update_one({"username": username}, {"$set": {"password": hash_password(req.new_password)}})
    return {"message": "Password updated successfully"}


@app.put("/profile/username")
def change_username(req: ChangeUsernameRequest, username: str = Depends(get_current_user)):
    if users_col is None:
        raise HTTPException(500, "MongoDB not configured")
    user = users_col.find_one({"username": username})
    if not user or not verify_password(req.current_password, user["password"]):
        raise HTTPException(401, "Password is incorrect")
    new_username = req.new_username.strip().lower()
    if len(new_username) < 3:
        raise HTTPException(400, "Username must be at least 3 characters")
    try:
        users_col.update_one({"username": username}, {"$set": {"username": new_username}})
        # also update accounts
        if accounts_col is not None:
            accounts_col.update_many({"username": username}, {"$set": {"username": new_username}})
        new_token = create_token(new_username)
        return {"message": "Username updated", "token": new_token, "username": new_username}
    except DuplicateKeyError:
        raise HTTPException(400, "Username already taken")


@app.delete("/profile/credentials")
def delete_aws_credentials(username: str = Depends(get_current_user)):
    """Delete all AWS credentials for a user but keep the account"""
    if accounts_col is None:
        raise HTTPException(500, "MongoDB not configured")
    result = accounts_col.delete_many({"username": username})
    return {"message": f"Deleted {result.deleted_count} AWS account(s)", "deleted": result.deleted_count}


@app.get("/instances")
def get_all_instances():
    return list_instances()

@app.get("/instances/running")
def get_running():
    return list_instances("running")

@app.get("/instances/stopped")
def get_stopped():
    return list_instances("stopped")