# AWS Infrastructure Query Platform

Natural language → Groq LLaMA-3 → Boto3 → Live AWS Data

---

## Project Structure

```
aws-query-platform/
├── backend/
│   ├── main.py            ← FastAPI app (all Boto3 logic)
│   ├── requirements.txt
│   └── .env               ← AWS + Groq keys (never commit this)
├── frontend/
│   ├── public/
│   │   └── index.html
│   ├── src/
│   │   ├── index.js
│   │   └── App.jsx        ← React UI
│   ├── package.json
│   └── .env               ← REACT_APP_ keys
└── README.md
```

---

## Setup — Backend

### 1. Fill in your credentials

Edit `backend/.env`:
```
AWS_ACCESS_KEY_ID=AKIAxxxxxxxxxxxxxxxx
AWS_SECRET_ACCESS_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AWS_REGION=ap-south-1
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx
```

### 2. Install dependencies & run

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### 3. Verify AWS connection

Open http://localhost:8000/health — you should see:
```json
{
  "status": "ok",
  "aws_connected": true,
  "account_id": "123456789012",
  "arn": "arn:aws:iam::...",
  "region": "ap-south-1"
}
```

---

## Setup — Frontend

### 1. Fill in your Groq key

Edit `frontend/.env`:
```
REACT_APP_GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxx
REACT_APP_BACKEND_URL=http://localhost:8000
```

### 2. Install dependencies & run

```bash
cd frontend
npm install
npm start
```

Open http://localhost:3000

---

## AWS IAM Permissions Required

Your AWS user/role needs at minimum:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:DescribeInstanceTypes",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeVolumes",
        "cloudwatch:GetMetricStatistics",
        "cloudwatch:GetMetricData",
        "cloudwatch:ListMetrics",
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## Available Tools (what Groq can call)

| Tool | What it does |
|------|-------------|
| `list_instances` | List EC2 instances, filter by state |
| `get_instance_by_name` | Get instance details by Name tag |
| `get_cpu_metrics` | CPU avg/max % from CloudWatch |
| `list_high_cpu_instances` | Instances above CPU threshold |
| `get_instance_status` | System + instance health checks |
| `list_security_groups` | SGs with inbound/outbound rules |
| `list_volumes` | EBS volumes with attachment info |
| `get_memory_metrics` | Memory % (needs CloudWatch Agent) |

---

## Example Queries

```
Show all running instances
What is the public IP of Lab1?
List instances using more than 70% CPU
Show all EBS volumes
What are my security groups?
Get health status of i-0abc123
Memory usage of DB-Primary
Show stopped instances
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service info |
| GET | `/health` | AWS connectivity check |
| POST | `/aws` | Execute an AWS tool |
| GET | `/tools` | List available tools |

### POST /aws — Body format:
```json
{
  "tool": "list_instances",
  "args": { "state": "running" }
}
```

---

## Architecture

```
Browser (React)
    ↕  Groq API (LLaMA-3 70B Tool Use)
    ↕  POST /aws
FastAPI Backend
    ↕  boto3
AWS (EC2 + CloudWatch + STS)
```
