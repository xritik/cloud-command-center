"""
AWS Infrastructure Query Platform - FastAPI Backend
----------------------------------------------------
Fully agentic architecture. There is NO fixed/hardcoded list of AWS tools.
Every user query is answered by the agent (agent.py): an LLM generates a
fresh, read-only Boto3 function for the specific question asked, the
generated code is statically validated for safety, then executed in a
sandboxed thread against the user's real AWS credentials.

Run: uvicorn main:app --reload --port 8000
"""

import os
import logging
from datetime import datetime, timedelta

# Third-party imports
import bcrypt
import boto3
from cryptography.fernet import Fernet
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from groq import Groq
from jose import JWTError, jwt
from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from pydantic import BaseModel

import agent  # the fully-agentic code-gen + validate + execute engine

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="AWS Query Platform - Agentic", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")

GROQ_KEYS = [
    v for k, v in sorted(os.environ.items())
    if k.startswith("GROQ_KEY_") and v.strip()
]
if not GROQ_KEYS and os.getenv("GROQ_API_KEY"):
    GROQ_KEYS = [os.getenv("GROQ_API_KEY")]

logger.info(f"Groq keys loaded: {len(GROQ_KEYS)}")

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

ENCRYPT_KEY = os.getenv("ENCRYPT_KEY", Fernet.generate_key().decode())
fernet = Fernet(ENCRYPT_KEY.encode() if isinstance(ENCRYPT_KEY, str) else ENCRYPT_KEY)


def encrypt_val(val):
    return fernet.encrypt(val.encode()).decode()


def decrypt_val(val):
    return fernet.decrypt(val.encode()).decode()


bearer_scheme = HTTPBearer()


def hash_password(password):
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password, hashed):
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(username):
    payload = {"sub": username, "exp": datetime.utcnow() + timedelta(hours=JWT_EXPIRE_H)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expired or invalid")


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


class AgentRequest(BaseModel):
    query: str
    region: str = "ap-south-1"
    account_id: str = ""
    access_key: str = ""   # fallback: direct credentials (optional)
    secret_key: str = ""   # fallback: direct credentials (optional)


_groq_key_idx = 0


def call_llm(messages):
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
                temperature=0,
                max_tokens=4096,
            )
            _groq_key_idx = idx
            logger.info(f"Groq key {idx + 1}/{len(GROQ_KEYS)} succeeded")
            return response
        except Exception as e:
            err_str = str(e).lower()
            if any(x in err_str for x in ["rate limit", "quota", "429"]):
                logger.warning(f"Groq key {idx + 1} rate-limited, trying next...")
                _groq_key_idx = (idx + 1) % len(GROQ_KEYS)
                continue
            logger.warning(f"Groq key {idx + 1} skipped: {str(e)[:100]}")
            _groq_key_idx = (idx + 1) % len(GROQ_KEYS)
            continue

    raise HTTPException(429, "All Groq API keys are rate-limited or invalid. Add more keys or wait a minute.")


def _groq_caller_for_agent(messages, tools=None):
    return call_llm(messages)


@app.get("/")
def root():
    return {"status": "ok", "service": "AWS Query Platform (Agentic)", "region": AWS_REGION}


@app.get("/regions")
def list_regions(username: str = Depends(get_current_user)):
    return {"regions": [
        "ap-south-1", "ap-south-2", "ap-southeast-1", "ap-southeast-2",
        "ap-northeast-1", "ap-northeast-2", "ap-northeast-3",
        "us-east-1", "us-east-2", "us-west-1", "us-west-2",
        "eu-west-1", "eu-west-2", "eu-west-3", "eu-central-1",
        "ca-central-1", "sa-east-1", "af-south-1", "me-south-1"
    ]}


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "aws_connected": True,
        "groq_keys": len(GROQ_KEYS),
        "message": "Fully agentic - AWS credentials are provided per-user at login",
    }


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


@app.post("/agent")
def agent_query(req: AgentRequest, username: str = Depends(get_current_user)):
    """
    The only way this app talks to AWS. Resolves AWS credentials by:
    1. account_id → looks up + decrypts from MongoDB (preferred)
    2. direct access_key/secret_key in request body (fallback)
    3. AWS_ACCESS_KEY_ID/SECRET from .env (last resort)
    """
    ak = None
    sk = None

    # Priority 1: look up account from MongoDB using account_id
    if req.account_id and accounts_col is not None:
        from bson import ObjectId
        try:
            acc = accounts_col.find_one({
                "_id": ObjectId(req.account_id),
                "username": username
            })
            if acc:
                ak = decrypt_val(acc["access_key"])
                sk = decrypt_val(acc["secret_key"])
                logger.info(f"[agent] Using account '{acc['label']}' for user '{username}'")
        except Exception as e:
            logger.warning(f"[agent] Failed to load account {req.account_id}: {e}")

    # Priority 2: direct credentials sent in request
    if not ak and req.access_key:
        ak = req.access_key
        sk = req.secret_key

    # Priority 3: .env fallback
    if not ak:
        ak = os.getenv("AWS_ACCESS_KEY_ID")
        sk = os.getenv("AWS_SECRET_ACCESS_KEY")

    if not ak or not sk:
        raise HTTPException(400, "No AWS credentials available. Please add an AWS account in Profile → Accounts.")

    logger.info(f"[agent] User '{username}' query: {req.query!r} | region={req.region}")

    return agent.run_agent_query(
        query=req.query,
        region=req.region,
        access_key=ak,
        secret_key=sk,
        groq_caller=_groq_caller_for_agent,
    )


@app.post("/accounts/add")
def add_account(req: AWSAccountRequest, username: str = Depends(get_current_user)):
    if accounts_col is None:
        raise HTTPException(500, "MongoDB not configured")
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
        if accounts_col is not None:
            accounts_col.update_many({"username": username}, {"$set": {"username": new_username}})
        new_token = create_token(new_username)
        return {"message": "Username updated", "token": new_token, "username": new_username}
    except DuplicateKeyError:
        raise HTTPException(400, "Username already taken")


@app.delete("/profile/credentials")
def delete_aws_credentials(username: str = Depends(get_current_user)):
    if accounts_col is None:
        raise HTTPException(500, "MongoDB not configured")
    result = accounts_col.delete_many({"username": username})
    return {"message": f"Deleted {result.deleted_count} AWS account(s)", "deleted": result.deleted_count}