from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from bson import ObjectId
import hashlib
import secrets

from database import get_db
from security import (
    verify_password, create_access_token, create_refresh_token, set_auth_cookies,
    check_lockout, record_failed_login, clear_login_attempts, audit_log,
    admin_network_allowed, generate_totp_secret, verify_totp,
)

router = APIRouter(prefix="/api/admin-auth", tags=["admin-auth"])


class AdminLoginIn(BaseModel):
    email: EmailStr
    password: str


class AdminOtpIn(BaseModel):
    challenge: str
    code: str


class AdminSetupIn(BaseModel):
    challenge: str
    code: str


def _challenge_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _issue_admin_session(response: Response, user: dict):
    uid = str(user["_id"])
    email = user["email"]
    access = create_access_token(uid, email, "admin")
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    await audit_log("admin_2fa_login", uid, email, "user", uid)
    return {
        "id": uid, "email": email, "name": user.get("name", ""),
        "role": "admin", "two_factor_enabled": True,
    }


@router.post("/login")
async def admin_login(data: AdminLoginIn, request: Request):
    if not admin_network_allowed(request):
        raise HTTPException(status_code=403, detail="Admin login is not allowed from this network")

    db = get_db()
    email = data.email.lower().strip()
    ip = request.client.host if request.client else "unknown"
    identifier = f"admin:{ip}:{email}"
    await check_lockout(identifier)

    user = await db.users.find_one({"email": email, "role": "admin"})
    if not user or not verify_password(data.password, user.get("password_hash", "")):
        await record_failed_login(identifier)
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    if user.get("disabled"):
        raise HTTPException(status_code=403, detail="Admin account disabled")

    await clear_login_attempts(identifier)
    now = datetime.now(timezone.utc)

    # First-time setup: password alone never creates an authenticated admin session.
    if not user.get("two_factor_secret"):
        challenge = secrets.token_urlsafe(32)
        await db.admin_login_challenges.insert_one({
            "token_hash": _challenge_hash(challenge),
            "user_id": str(user["_id"]),
            "purpose": "setup",
            "expires_at": now + timedelta(minutes=10),
            "used": False,
            "created_at": now,
        })
        secret = generate_totp_secret()
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"two_factor_pending_secret": secret}})
        issuer = "ZEROAXIS"
        label = f"{issuer}:{email}"
        otp_uri = f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
        await audit_log("admin_2fa_setup_started", str(user["_id"]), email, "user", str(user["_id"]))
        return {"two_factor_setup_required": True, "challenge": challenge, "secret": secret, "otpauth_uri": otp_uri}

    challenge = secrets.token_urlsafe(32)
    await db.admin_login_challenges.insert_one({
        "token_hash": _challenge_hash(challenge),
        "user_id": str(user["_id"]),
        "purpose": "login",
        "expires_at": now + timedelta(minutes=5),
        "used": False,
        "created_at": now,
    })
    return {"two_factor_required": True, "challenge": challenge}


@router.post("/setup")
async def admin_setup_2fa(data: AdminSetupIn, response: Response, request: Request):
    if not admin_network_allowed(request):
        raise HTTPException(status_code=403, detail="Admin login is not allowed from this network")
    db = get_db()
    rec = await db.admin_login_challenges.find_one({
        "token_hash": _challenge_hash(data.challenge),
        "purpose": "setup",
        "used": False,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if not rec:
        raise HTTPException(status_code=400, detail="Setup session is invalid or expired")
    user = await db.users.find_one({"_id": ObjectId(rec["user_id"]), "role": "admin"})
    if not user:
        raise HTTPException(status_code=400, detail="Admin account not found")
    secret = user.get("two_factor_pending_secret", "")
    if not verify_totp(secret, data.code):
        raise HTTPException(status_code=400, detail="Invalid authenticator code")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {
        "two_factor_secret": secret,
        "two_factor_enabled": True,
        "two_factor_pending_secret": None,
    }, "$unset": {"two_factor_pending_secret": ""}})
    await db.admin_login_challenges.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    return await _issue_admin_session(response, user)


@router.post("/verify")
async def admin_verify_2fa(data: AdminOtpIn, response: Response, request: Request):
    if not admin_network_allowed(request):
        raise HTTPException(status_code=403, detail="Admin login is not allowed from this network")
    db = get_db()
    rec = await db.admin_login_challenges.find_one({
        "token_hash": _challenge_hash(data.challenge),
        "purpose": "login",
        "used": False,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if not rec:
        raise HTTPException(status_code=400, detail="Login session is invalid or expired")
    user = await db.users.find_one({"_id": ObjectId(rec["user_id"]), "role": "admin"})
    if not user or not verify_totp(user.get("two_factor_secret", ""), data.code):
        raise HTTPException(status_code=401, detail="Invalid authenticator code")
    await db.admin_login_challenges.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    return await _issue_admin_session(response, user)
