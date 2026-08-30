import os
import bcrypt
import jwt
from datetime import datetime, timezone, timedelta
from fastapi import HTTPException, Request, Depends
from bson import ObjectId
from database import get_db

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_MINUTES = 60 * 12  # 12h
REFRESH_TOKEN_DAYS = 7
MAX_LOGIN_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def get_jwt_secret() -> str:
    return os.environ["JWT_SECRET"]


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_access_token(user_id: str, email: str, role: str) -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_MINUTES),
        "type": "access",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    payload = {
        "sub": user_id,
        "exp": datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_DAYS),
        "type": "refresh",
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGORITHM)


def set_auth_cookies(response, access: str, refresh: str):
    response.set_cookie("access_token", access, httponly=True, secure=True, samesite="none",
                        max_age=ACCESS_TOKEN_MINUTES * 60, path="/")
    response.set_cookie("refresh_token", refresh, httponly=True, secure=True, samesite="none",
                        max_age=REFRESH_TOKEN_DAYS * 86400, path="/")


def clear_auth_cookies(response):
    response.delete_cookie("access_token", path="/")
    response.delete_cookie("refresh_token", path="/")


def _extract_token(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return token


async def get_current_user(request: Request) -> dict:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    db = get_db()
    try:
        user = await db.users.find_one({"_id": ObjectId(payload["sub"])})
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid user")
    if not user or user.get("disabled"):
        raise HTTPException(status_code=401, detail="User not found")
    user["id"] = str(user["_id"])
    user.pop("_id", None)
    user.pop("password_hash", None)
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


async def check_lockout(identifier: str) -> None:
    db = get_db()
    rec = await db.login_attempts.find_one({"identifier": identifier})
    if not rec:
        return
    if rec.get("locked_until"):
        locked = rec["locked_until"]
        if isinstance(locked, str):
            locked = datetime.fromisoformat(locked)
        if locked > datetime.now(timezone.utc):
            raise HTTPException(status_code=429, detail=f"Too many attempts. Try again later.")


async def record_failed_login(identifier: str) -> None:
    db = get_db()
    rec = await db.login_attempts.find_one({"identifier": identifier})
    attempts = (rec.get("attempts", 0) if rec else 0) + 1
    update = {"attempts": attempts}
    if attempts >= MAX_LOGIN_ATTEMPTS:
        update["locked_until"] = (datetime.now(timezone.utc) + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
        update["attempts"] = 0
    await db.login_attempts.update_one(
        {"identifier": identifier}, {"$set": update}, upsert=True
    )


async def clear_login_attempts(identifier: str) -> None:
    db = get_db()
    await db.login_attempts.delete_one({"identifier": identifier})


async def audit_log(action: str, actor_id: str | None, actor_email: str | None,
                    target_type: str | None = None, target_id: str | None = None,
                    metadata: dict | None = None):
    db = get_db()
    await db.audit_logs.insert_one({
        "action": action,
        "actor_id": actor_id,
        "actor_email": actor_email,
        "target_type": target_type,
        "target_id": target_id,
        "metadata": metadata or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
