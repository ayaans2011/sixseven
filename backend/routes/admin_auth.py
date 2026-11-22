import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from bson import ObjectId
import hashlib
import hmac
import secrets

from database import get_db
from services.email import send_admin_login_otp
from security import (
    verify_password, create_access_token, create_refresh_token, set_auth_cookies,
    check_lockout, record_failed_login, clear_login_attempts, audit_log,
    admin_network_allowed, get_jwt_secret,
)

router = APIRouter(prefix="/api/admin-auth", tags=["admin-auth"])


class AdminLoginIn(BaseModel):
    email: EmailStr
    password: str


class AdminOtpIn(BaseModel):
    challenge: str
    code: str


def _digest(value: str) -> str:
    # Keyed digest prevents a database-only attacker from cheaply enumerating 6-digit OTPs.
    key = get_jwt_secret().encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


async def _issue_admin_session(response: Response, user: dict):
    uid = str(user["_id"])
    email = user["email"]
    access = create_access_token(uid, email, "admin")
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    await audit_log("admin_email_otp_login", uid, email, "user", uid)
    return {"id": uid, "email": email, "name": user.get("name", ""), "role": "admin",
            "two_factor_enabled": True, "access_token": access}


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
    if not user or user.get("disabled") or not await asyncio.to_thread(verify_password, data.password, user.get("password_hash", "")):
        await record_failed_login(identifier)
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    await clear_login_attempts(identifier)

    now = datetime.now(timezone.utc)
    recent = await db.admin_login_challenges.count_documents({
        "user_id": str(user["_id"]),
        "purpose": "email_otp_login",
        "created_at": {"$gt": now - timedelta(minutes=15)},
    })
    if recent >= 3:
        raise HTTPException(status_code=429, detail="Too many email code requests. Try again in 15 minutes.")

    # Invalidate earlier pending codes so only the newest challenge can be used.
    await db.admin_login_challenges.update_many(
        {"user_id": str(user["_id"]), "purpose": "email_otp_login", "used": False},
        {"$set": {"used": True}},
    )
    challenge = secrets.token_urlsafe(32)
    otp = f"{secrets.randbelow(1_000_000):06d}"
    await db.admin_login_challenges.insert_one({
        "token_hash": _digest(challenge),
        "otp_hash": _digest(otp),
        "user_id": str(user["_id"]),
        "purpose": "email_otp_login",
        "expires_at": now + timedelta(minutes=5),
        "created_at": now,
        "used": False,
        "attempts": 0,
    })

    sent = await send_admin_login_otp(
        to_email=email, name=user.get("name", ""), otp=otp
    )
    if not sent:
        await db.admin_login_challenges.update_one(
            {"token_hash": _digest(challenge), "used": False},
            {"$set": {"used": True}},
        )
        raise HTTPException(status_code=503, detail="Email delivery is temporarily unavailable. Please try again.")
    await audit_log("admin_email_otp_requested", str(user["_id"]), email, "user", str(user["_id"]))
    return {"two_factor_required": True, "challenge": challenge,
            "message": "A six-digit sign-in code has been sent to your registered admin email."}


@router.post("/verify")
async def admin_verify_email_otp(data: AdminOtpIn, response: Response, request: Request):
    if not admin_network_allowed(request):
        raise HTTPException(status_code=403, detail="Admin login is not allowed from this network")
    if not data.code.isdigit() or len(data.code) != 6:
        raise HTTPException(status_code=400, detail="Enter the six-digit email code.")

    db = get_db()
    rec = await db.admin_login_challenges.find_one({
        "token_hash": _digest(data.challenge),
        "purpose": "email_otp_login",
        "used": False,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if not rec:
        raise HTTPException(status_code=400, detail="Sign-in session is invalid or expired. Start login again.")
    if rec.get("attempts", 0) >= 5:
        await db.admin_login_challenges.update_one(
            {"_id": rec["_id"], "used": False}, {"$set": {"used": True}}
        )
        raise HTTPException(status_code=429, detail="Too many incorrect codes. Start login again.")

    if not hmac.compare_digest(_digest(data.code), rec.get("otp_hash", "")):
        result = await db.admin_login_challenges.update_one(
            {"_id": rec["_id"], "used": False}, {"$inc": {"attempts": 1}}
        )
        if result.matched_count != 1:
            raise HTTPException(status_code=400, detail="Sign-in session is invalid or expired.")
        raise HTTPException(status_code=401, detail="Incorrect email verification code.")

    # Consume the challenge atomically to prevent concurrent/replayed verification.
    consumed = await db.admin_login_challenges.update_one(
        {"_id": rec["_id"], "used": False, "expires_at": {"$gt": datetime.now(timezone.utc)}},
        {"$set": {"used": True, "verified_at": datetime.now(timezone.utc)}},
    )
    if consumed.modified_count != 1:
        raise HTTPException(status_code=400, detail="Sign-in session is invalid or expired. Start login again.")

    user = await db.users.find_one({
        "_id": ObjectId(rec["user_id"]), "role": "admin", "disabled": {"$ne": True}
    })
    if not user:
        raise HTTPException(status_code=403, detail="Admin account is disabled or unavailable.")

    # Retire legacy authenticator secrets after the first successful email-OTP login.
    if any(k in user for k in ("two_factor_secret", "two_factor_pending_secret", "two_factor_enabled")):
        await db.users.update_one({"_id": user["_id"]}, {
            "$unset": {"two_factor_secret": "", "two_factor_pending_secret": "", "two_factor_enabled": ""}
        })
    return await _issue_admin_session(response, user)
