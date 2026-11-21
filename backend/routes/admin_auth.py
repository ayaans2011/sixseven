from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr
from bson import ObjectId
import hashlib
import secrets
import base64
from io import BytesIO
import qrcode
from qrcode.image.svg import SvgPathImage

from database import get_db
from services.email import admin_2fa_recovery_otp
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


class AdminRecoveryRequestIn(BaseModel):
    email: EmailStr
    password: str


class AdminRecoveryVerifyIn(BaseModel):
    recovery_token: str
    code: str


def _challenge_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def _record_challenge_failure(db, rec: dict):
    await db.admin_login_challenges.update_one(
        {"_id": rec["_id"], "used": False},
        {"$inc": {"attempts": 1}},
    )
    current = await db.admin_login_challenges.find_one({"_id": rec["_id"]})
    if current and current.get("attempts", 0) >= 5:
        await db.admin_login_challenges.update_one(
            {"_id": rec["_id"]},
            {"$set": {"used": True}},
        )
        raise HTTPException(status_code=429, detail="Too many invalid authenticator codes. Start login again.")


async def _issue_admin_session(response: Response, user: dict):
    uid = str(user["_id"])
    email = user["email"]
    access = create_access_token(uid, email, "admin")
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    await audit_log("admin_2fa_login", uid, email, "user", uid)
    return {"id": uid, "email": email, "name": user.get("name", ""), "role": "admin", "two_factor_enabled": True, "access_token": access}


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

    if not user.get("two_factor_secret"):
        challenge = secrets.token_urlsafe(32)
        await db.admin_login_challenges.insert_one({
            "token_hash": _challenge_hash(challenge), "user_id": str(user["_id"]),
            "purpose": "setup", "expires_at": now + timedelta(minutes=10),
            "used": False, "attempts": 0, "created_at": now,
        })
        secret = user.get("two_factor_pending_secret") or generate_totp_secret()
        await db.users.update_one({"_id": user["_id"]}, {"$set": {"two_factor_pending_secret": secret}})
        issuer = "ZEROAXIS"
        label = f"{issuer}:{email}"
        otp_uri = f"otpauth://totp/{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
        qr = qrcode.make(otp_uri, image_factory=SvgPathImage, box_size=8, border=4)
        qr_buffer = BytesIO()
        qr.save(qr_buffer)
        qr_code_svg_base64 = base64.b64encode(qr_buffer.getvalue()).decode("ascii")
        await audit_log("admin_2fa_setup_started", str(user["_id"]), email, "user", str(user["_id"]))
        return {"two_factor_setup_required": True, "challenge": challenge, "secret": secret, "otpauth_uri": otp_uri, "qr_code_svg_base64": qr_code_svg_base64}

    challenge = secrets.token_urlsafe(32)
    await db.admin_login_challenges.insert_one({
        "token_hash": _challenge_hash(challenge), "user_id": str(user["_id"]),
        "purpose": "login", "expires_at": now + timedelta(minutes=5),
        "used": False, "attempts": 0, "created_at": now,
    })
    return {"two_factor_required": True, "challenge": challenge}


@router.post("/recovery/request")
async def request_admin_2fa_recovery(data: AdminRecoveryRequestIn, request: Request):
    if not admin_network_allowed(request):
        raise HTTPException(status_code=403, detail="Admin login is not allowed from this network")
    db = get_db()
    email = data.email.lower().strip()
    user = await db.users.find_one({"email": email, "role": "admin"})
    if not user or user.get("disabled") or not verify_password(data.password, user.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    if not user.get("two_factor_secret"):
        raise HTTPException(status_code=400, detail="Authenticator setup is not active for this account")
    now = datetime.now(timezone.utc)
    recent = await db.admin_2fa_recovery_otps.count_documents({
        "user_id": str(user["_id"]), "created_at": {"$gt": now - timedelta(minutes=15)}
    })
    if recent >= 3:
        raise HTTPException(status_code=429, detail="Too many recovery requests. Try again in 15 minutes.")
    otp = f"{secrets.randbelow(1000000):06d}"
    recovery_token = secrets.token_urlsafe(32)
    await db.admin_2fa_recovery_otps.update_many(
        {"user_id": str(user["_id"]), "used": False}, {"$set": {"used": True}}
    )
    await db.admin_2fa_recovery_otps.insert_one({
        "user_id": str(user["_id"]),
        "token_hash": _challenge_hash(recovery_token),
        "otp_hash": hashlib.sha256(otp.encode("utf-8")).hexdigest(),
        "created_at": now,
        "expires_at": now + timedelta(minutes=10),
        "used": False,
        "attempts": 0,
    })
    admin_2fa_recovery_otp(to_email=email, name=user.get("name", ""), otp=otp)
    await audit_log("admin_2fa_recovery_requested", str(user["_id"]), email, "user", str(user["_id"]))
    return {"message": "If the admin credentials are valid, a recovery code has been sent to the registered email address.", "recovery_token": recovery_token}


@router.post("/recovery/verify")
async def verify_admin_2fa_recovery(data: AdminRecoveryVerifyIn, response: Response, request: Request):
    if not admin_network_allowed(request):
        raise HTTPException(status_code=403, detail="Admin login is not allowed from this network")
    db = get_db()
    now = datetime.now(timezone.utc)
    rec = await db.admin_2fa_recovery_otps.find_one({
        "token_hash": _challenge_hash(data.recovery_token),
        "used": False,
        "expires_at": {"$gt": now},
    })
    if not rec:
        raise HTTPException(status_code=400, detail="Recovery session is invalid or expired. Request a new code.")
    if rec.get("attempts", 0) >= 5:
        await db.admin_2fa_recovery_otps.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
        raise HTTPException(status_code=429, detail="Too many invalid recovery codes. Request a new code.")
    supplied = hashlib.sha256(data.code.encode("utf-8")).hexdigest() if data.code.isdigit() and len(data.code) == 6 else ""
    if not secrets.compare_digest(supplied, rec.get("otp_hash", "")):
        await db.admin_2fa_recovery_otps.update_one({"_id": rec["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=400, detail="Invalid or expired recovery code")
    user = await db.users.find_one({
        "_id": ObjectId(rec["user_id"]), "role": "admin", "disabled": {"$ne": True}
    })
    if not user or not user.get("two_factor_secret"):
        await db.admin_2fa_recovery_otps.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
        raise HTTPException(status_code=400, detail="Admin recovery is no longer available")
    # Only after email OTP verification, invalidate the old authenticator secret
    # and begin a fresh setup. No admin session is issued by this recovery flow.
    new_secret = generate_totp_secret()
    await db.users.update_one({"_id": user["_id"]}, {
        "$set": {"two_factor_pending_secret": new_secret},
        "$unset": {"two_factor_secret": "", "two_factor_enabled": ""},
    })
    await db.admin_login_challenges.update_many(
        {"user_id": str(user["_id"]), "used": False}, {"$set": {"used": True}}
    )
    challenge = secrets.token_urlsafe(32)
    await db.admin_login_challenges.insert_one({
        "token_hash": _challenge_hash(challenge),
        "user_id": str(user["_id"]),
        "purpose": "setup",
        "expires_at": now + timedelta(minutes=10),
        "used": False,
        "attempts": 0,
        "created_at": now,
    })
    await db.admin_2fa_recovery_otps.update_one({"_id": rec["_id"]}, {"$set": {"used": True, "verified_at": now}})
    issuer = "ZEROAXIS"
    label = f"{issuer}:{user['email']}"
    otp_uri = f"otpauth://totp/{label}?secret={new_secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
    qr = qrcode.make(otp_uri, image_factory=SvgPathImage, box_size=8, border=4)
    qr_buffer = BytesIO()
    qr.save(qr_buffer)
    qr_code_svg_base64 = base64.b64encode(qr_buffer.getvalue()).decode("ascii")
    await audit_log("admin_2fa_recovery_verified", str(user["_id"]), user["email"], "user", str(user["_id"]))
    return {
        "two_factor_setup_required": True,
        "challenge": challenge,
        "secret": new_secret,
        "otpauth_uri": otp_uri,
        "qr_code_svg_base64": qr_code_svg_base64,
        "message": "Old authenticator disabled. Scan the new QR code and verify a fresh code to finish setup.",
    }


@router.post("/setup")
async def admin_setup_2fa(data: AdminSetupIn, response: Response, request: Request):
    if not admin_network_allowed(request):
        raise HTTPException(status_code=403, detail="Admin login is not allowed from this network")
    db = get_db()
    rec = await db.admin_login_challenges.find_one({
        "token_hash": _challenge_hash(data.challenge), "purpose": "setup",
        "used": False, "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if not rec:
        raise HTTPException(status_code=400, detail="Setup session is invalid or expired")
    user = await db.users.find_one({"_id": ObjectId(rec["user_id"]), "role": "admin", "disabled": {"$ne": True}})
    if not user:
        raise HTTPException(status_code=400, detail="Admin account not found or disabled")
    secret = user.get("two_factor_pending_secret", "")
    if not verify_totp(secret, data.code):
        await _record_challenge_failure(db, rec)
        raise HTTPException(status_code=400, detail="Invalid authenticator code")
    await db.users.update_one({"_id": user["_id"]}, {"$set": {
        "two_factor_secret": secret,
        "two_factor_enabled": True,
    }, "$unset": {"two_factor_pending_secret": ""}})
    await db.admin_login_challenges.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    return await _issue_admin_session(response, user)


@router.post("/verify")
async def admin_verify_2fa(data: AdminOtpIn, response: Response, request: Request):
    if not admin_network_allowed(request):
        raise HTTPException(status_code=403, detail="Admin login is not allowed from this network")
    db = get_db()
    rec = await db.admin_login_challenges.find_one({
        "token_hash": _challenge_hash(data.challenge), "purpose": "login",
        "used": False, "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if not rec:
        raise HTTPException(status_code=400, detail="Login session is invalid or expired")
    user = await db.users.find_one({"_id": ObjectId(rec["user_id"]), "role": "admin"})
    if not user or user.get("disabled") or not verify_totp(user.get("two_factor_secret", ""), data.code):
        await _record_challenge_failure(db, rec)
        raise HTTPException(status_code=401, detail="Invalid authenticator code")
    await db.admin_login_challenges.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    return await _issue_admin_session(response, user)
