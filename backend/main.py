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

def get_ec2():
    return boto3.client(
        "ec2", region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

def get_cw():
    return boto3.client(
        "cloudwatch", region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── MongoDB Atlas ─────────────────────────────────────────────────────────────
MONGO_URI    = os.getenv("MONGO_URI")
JWT_SECRET   = os.getenv("JWT_SECRET", "change-this-secret-in-production")
JWT_ALGO     = "HS256"
JWT_EXPIRE_H = 24

_mongo       = MongoClient(MONGO_URI) if MONGO_URI else None
db           = _mongo["cloudCommansCenter"] if _mongo is not None else None
users_col    = db["users"] if db is not None else None

if users_col is not None:
    users_col.create_index("username", unique=True)

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

class DirectToolRequest(BaseModel):
    tool: str
    args: dict = {}

class AuthRequest(BaseModel):
    username: str
    password: str

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
def list_instances(state: Optional[str] = None) -> dict:
    try:
        ec2 = get_ec2()
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


def get_instance_by_name(name: str) -> dict:
    try:
        ec2 = get_ec2()
        resp = ec2.describe_instances(Filters=[{"Name": "tag:Name", "Values": [name]}])
        for r in resp["Reservations"]:
            for inst in r["Instances"]:
                return {"found": True, "instance": parse_instance(inst)}
        return {"found": False, "message": f"No instance with Name tag '{name}' found."}
    except ClientError as e:
        raise HTTPException(500, f"AWS Error: {e.response['Error']['Message']}")


def get_cpu_metrics(instance_id: str, hours: float = 1) -> dict:
    try:
        cw = get_cw()
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


def list_high_cpu_instances(threshold: float = 70) -> dict:
    all_data = list_instances(state="running")
    results = []
    for inst in all_data.get("instances", []):
        metrics = get_cpu_metrics(inst["id"], hours=1)
        cpu = metrics.get("cpu_avg")
        if cpu is not None and cpu >= threshold:
            results.append({**inst, "cpu_avg": cpu})
    return {"threshold": threshold, "instances": results, "count": len(results)}


def get_instance_status(instance_id: str) -> dict:
    try:
        ec2 = get_ec2()
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


def list_security_groups(instance_id: Optional[str] = None) -> dict:
    try:
        ec2 = get_ec2()
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


def list_volumes(instance_id: Optional[str] = None) -> dict:
    try:
        ec2 = get_ec2()
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


def get_memory_metrics(instance_id: str, hours: float = 1) -> dict:
    try:
        cw = get_cw()
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
TOOL_MAP = {
    "list_instances":          lambda a: list_instances(a.get("state")),
    "get_instance_by_name":    lambda a: get_instance_by_name(a["name"]),
    "get_cpu_metrics":         lambda a: get_cpu_metrics(a["instance_id"], a.get("hours", 1)),
    "list_high_cpu_instances": lambda a: list_high_cpu_instances(a.get("threshold", 70)),
    "get_instance_status":     lambda a: get_instance_status(a["instance_id"]),
    "list_security_groups":    lambda a: list_security_groups(a.get("instance_id")),
    "list_volumes":            lambda a: list_volumes(a.get("instance_id")),
    "get_memory_metrics":      lambda a: get_memory_metrics(a["instance_id"], a.get("hours", 1)),
}

def run_tool(tool_name: str, args: dict) -> dict:
    if tool_name not in TOOL_MAP:
        return {"error": f"Unknown tool: {tool_name}"}
    logger.info(f"Tool: {tool_name} | Args: {args}")
    return TOOL_MAP[tool_name](args)


# ── API Routes ────────────────────────────────────────────────────────────────
@app.get("/")
def root():
    return {"status": "ok", "service": "AWS Query Platform", "region": AWS_REGION}


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


@app.post("/chat")
async def chat(req: ChatRequest, username: str = Depends(get_current_user)):
    system_msg = {
        "role": "system",
        "content": (
            f"You are an expert AWS Infrastructure Assistant for region {AWS_REGION}. "
            "Use the provided tools to fetch real AWS data. Never guess or fabricate details. "
            "After calling tools, summarize clearly and concisely. "
            "If an instance has no public IP, say so explicitly."
        )
    }
    messages = [system_msg] + req.history + [{"role": "user", "content": req.message}]
    tool_calls_log = []

    for _ in range(10):
        response = groq_client.chat.completions.create(
            model="llama3-groq-70b-8192-tool-use-preview",
            messages=messages,
            tools=AWS_TOOLS,
            tool_choice="auto",
            temperature=0.1,
            max_tokens=2048,
        )
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
            result = run_tool(fn_name, fn_args)
            tool_calls_log.append({"tool": fn_name, "args": fn_args, "result": result})
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result)})

    return {"reply": "Reached max tool call limit.", "tool_calls": tool_calls_log}


@app.post("/tool")
def direct_tool(req: DirectToolRequest):
    return run_tool(req.tool, req.args)


@app.get("/instances")
def get_all_instances():
    return list_instances()

@app.get("/instances/running")
def get_running():
    return list_instances("running")

@app.get("/instances/stopped")
def get_stopped():
    return list_instances("stopped")