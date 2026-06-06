"""
AWS Query Platform - FastAPI Backend
Connects Groq LLM tool-use to real AWS Boto3 calls.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import boto3
import json
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="AWS Query Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # tighten in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── AWS clients (credentials come from .env or IAM role) ────────────────────
AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

def get_ec2():
    return boto3.client(
        "ec2",
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )

def get_cw():
    return boto3.client(
        "cloudwatch",
        region_name=AWS_REGION,
        aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
    )


# ── Request model ────────────────────────────────────────────────────────────
class ToolRequest(BaseModel):
    tool: str
    args: dict


# ── Helper: parse instances from AWS response ────────────────────────────────
def parse_instances(reservations: list) -> list:
    instances = []
    for r in reservations:
        for inst in r["Instances"]:
            name = next(
                (t["Value"] for t in inst.get("Tags", []) if t["Key"] == "Name"),
                "Unnamed",
            )
            instances.append({
                "id":          inst["InstanceId"],
                "name":        name,
                "state":       inst["State"]["Name"],
                "type":        inst["InstanceType"],
                "public_ip":   inst.get("PublicIpAddress", "N/A"),
                "private_ip":  inst.get("PrivateIpAddress", "N/A"),
                "az":          inst.get("Placement", {}).get("AvailabilityZone", "N/A"),
                "launch_time": str(inst.get("LaunchTime", "")),
                "image_id":    inst.get("ImageId", "N/A"),
                "key_name":    inst.get("KeyName", "N/A"),
                "vpc_id":      inst.get("VpcId", "N/A"),
                "subnet_id":   inst.get("SubnetId", "N/A"),
            })
    return instances


# ── Tool implementations ─────────────────────────────────────────────────────

def list_instances(state: Optional[str] = None) -> dict:
    ec2 = get_ec2()
    filters = []
    if state and state != "all":
        filters = [{"Name": "instance-state-name", "Values": [state]}]
    resp = ec2.describe_instances(Filters=filters)
    instances = parse_instances(resp["Reservations"])
    return {"instances": instances, "count": len(instances)}


def get_instance_by_name(name: str) -> dict:
    ec2 = get_ec2()
    resp = ec2.describe_instances(
        Filters=[{"Name": "tag:Name", "Values": [name]}]
    )
    instances = parse_instances(resp["Reservations"])
    if not instances:
        return {"found": False, "message": f"No instance named '{name}' found."}
    return {"found": True, "instance": instances[0]}


def get_cpu_metrics(instance_id: str, hours: int = 1) -> dict:
    cw = get_cw()
    end = datetime.utcnow()
    start = end - timedelta(hours=hours)
    resp = cw.get_metric_statistics(
        Namespace="AWS/EC2",
        MetricName="CPUUtilization",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Average", "Maximum"],
    )
    datapoints = sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
    if not datapoints:
        return {
            "instance_id": instance_id,
            "message": "No CPU data available. Instance may be stopped.",
            "cpu_avg": 0,
            "cpu_max": 0,
        }
    latest = datapoints[-1]
    return {
        "instance_id": instance_id,
        "cpu_avg": round(latest["Average"], 2),
        "cpu_max": round(latest["Maximum"], 2),
        "period_hours": hours,
        "unit": "%",
        "datapoints": [
            {
                "time": str(d["Timestamp"]),
                "avg": round(d["Average"], 2),
                "max": round(d["Maximum"], 2),
            }
            for d in datapoints
        ],
    }


def list_high_cpu_instances(threshold: float = 70.0) -> dict:
    running = list_instances(state="running")
    results = []
    for inst in running["instances"]:
        metrics = get_cpu_metrics(inst["id"], hours=1)
        cpu = metrics.get("cpu_avg", 0)
        if cpu >= threshold:
            results.append({**inst, "cpu_avg": cpu, "cpu_max": metrics.get("cpu_max", 0)})
    return {
        "threshold": threshold,
        "instances": results,
        "count": len(results),
    }


def get_instance_status(instance_id: str) -> dict:
    ec2 = get_ec2()
    resp = ec2.describe_instance_status(
        InstanceIds=[instance_id],
        IncludeAllInstances=True,
    )
    statuses = resp.get("InstanceStatuses", [])
    if not statuses:
        return {"instance_id": instance_id, "error": "Instance not found"}
    s = statuses[0]
    return {
        "instance_id": instance_id,
        "state":            s["InstanceState"]["Name"],
        "instance_status":  s["InstanceStatus"]["Status"],
        "system_status":    s["SystemStatus"]["Status"],
        "instance_checks": [
            {"name": c["Name"], "status": c["Status"]}
            for c in s["InstanceStatus"].get("Details", [])
        ],
        "system_checks": [
            {"name": c["Name"], "status": c["Status"]}
            for c in s["SystemStatus"].get("Details", [])
        ],
    }


def list_security_groups(instance_id: Optional[str] = None) -> dict:
    ec2 = get_ec2()
    if instance_id:
        resp = ec2.describe_instances(InstanceIds=[instance_id])
        sg_ids = []
        for r in resp["Reservations"]:
            for inst in r["Instances"]:
                sg_ids += [sg["GroupId"] for sg in inst.get("SecurityGroups", [])]
        sg_resp = ec2.describe_security_groups(GroupIds=sg_ids) if sg_ids else {"SecurityGroups": []}
    else:
        sg_resp = ec2.describe_security_groups()

    groups = []
    for sg in sg_resp["SecurityGroups"]:
        groups.append({
            "id":          sg["GroupId"],
            "name":        sg["GroupName"],
            "description": sg["Description"],
            "vpc_id":      sg.get("VpcId", "N/A"),
            "inbound_rules": [
                {
                    "protocol": r.get("IpProtocol", "all"),
                    "from_port": r.get("FromPort", "N/A"),
                    "to_port":   r.get("ToPort", "N/A"),
                    "cidr": [ip["CidrIp"] for ip in r.get("IpRanges", [])],
                }
                for r in sg.get("IpPermissions", [])
            ],
            "outbound_rules": len(sg.get("IpPermissionsEgress", [])),
        })
    return {"groups": groups, "count": len(groups)}


def list_volumes(instance_id: Optional[str] = None) -> dict:
    ec2 = get_ec2()
    filters = []
    if instance_id:
        filters = [{"Name": "attachment.instance-id", "Values": [instance_id]}]
    resp = ec2.describe_volumes(Filters=filters)
    volumes = []
    for v in resp["Volumes"]:
        attachments = v.get("Attachments", [])
        volumes.append({
            "id":          v["VolumeId"],
            "size_gb":     v["Size"],
            "type":        v["VolumeType"],
            "state":       v["State"],
            "az":          v["AvailabilityZone"],
            "encrypted":   v.get("Encrypted", False),
            "iops":        v.get("Iops", "N/A"),
            "attached_to": attachments[0]["InstanceId"] if attachments else "Unattached",
            "device":      attachments[0]["Device"] if attachments else "N/A",
        })
    return {"volumes": volumes, "count": len(volumes)}


def get_memory_metrics(instance_id: str, hours: int = 1) -> dict:
    """Requires CloudWatch Agent installed on the instance."""
    cw = get_cw()
    end = datetime.utcnow()
    start = end - timedelta(hours=hours)
    resp = cw.get_metric_statistics(
        Namespace="CWAgent",
        MetricName="mem_used_percent",
        Dimensions=[{"Name": "InstanceId", "Value": instance_id}],
        StartTime=start,
        EndTime=end,
        Period=3600,
        Statistics=["Average"],
    )
    datapoints = sorted(resp.get("Datapoints", []), key=lambda x: x["Timestamp"])
    if not datapoints:
        return {
            "instance_id": instance_id,
            "message": "No memory data. CloudWatch Agent may not be installed.",
            "mem_avg": 0,
        }
    return {
        "instance_id": instance_id,
        "mem_avg": round(datapoints[-1]["Average"], 2),
        "unit": "%",
        "period_hours": hours,
    }


# ── Dispatch map ─────────────────────────────────────────────────────────────
TOOL_MAP = {
    "list_instances":       lambda a: list_instances(a.get("state")),
    "get_instance_by_name": lambda a: get_instance_by_name(a["name"]),
    "get_cpu_metrics":      lambda a: get_cpu_metrics(a["instance_id"], int(a.get("hours", 1))),
    "list_high_cpu_instances": lambda a: list_high_cpu_instances(float(a.get("threshold", 70))),
    "get_instance_status":  lambda a: get_instance_status(a["instance_id"]),
    "list_security_groups": lambda a: list_security_groups(a.get("instance_id")),
    "list_volumes":         lambda a: list_volumes(a.get("instance_id")),
    "get_memory_metrics":   lambda a: get_memory_metrics(a["instance_id"], int(a.get("hours", 1))),
}


# ── Routes ───────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "AWS Query Platform", "region": AWS_REGION}


@app.get("/health")
def health():
    try:
        sts = boto3.client(
            "sts",
            region_name=AWS_REGION,
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
        )
        identity = sts.get_caller_identity()
        return {
            "status": "ok",
            "aws_connected": True,
            "account_id": identity["Account"],
            "arn": identity["Arn"],
            "region": AWS_REGION,
        }
    except Exception as e:
        return {"status": "error", "aws_connected": False, "error": str(e)}


@app.post("/aws")
def run_aws_tool(req: ToolRequest):
    tool = req.tool
    args = req.args

    if tool not in TOOL_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}. Available: {list(TOOL_MAP.keys())}")

    try:
        result = TOOL_MAP[tool](args)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AWS call failed: {str(e)}")


@app.get("/tools")
def list_tools():
    return {"tools": list(TOOL_MAP.keys()), "count": len(TOOL_MAP)}
