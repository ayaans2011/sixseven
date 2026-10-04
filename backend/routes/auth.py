from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from bson import ObjectId
import secrets
import hashlib

from database import get_db
from security import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    set_auth_cookies, clear_auth_cookies, get_current_user,
    check_lockout, record_failed_login, clear_login_attempts, audit_log,
)
from models import RegisterIn, LoginIn, ForgotPasswordIn, ResetPasswordIn, RegisterOtpIn, ActivateAccountIn
from services.email import password_reset, registration_otp

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _serialize_user(u: dict) -> dict:
    return {
        "id": str(u["_id"]) if "_id" in u else u.get("id"),
        "email": u["email"],
        "name": u.get("name", ""),
        "role": u.get("role", "customer"),
        "phone": u.get("phone"),
        "address": u.get("address"),
        "company": u.get("company"),
        "created_at": u.get("created_at"),
    }


@router.post("/register")
async def register(data: RegisterIn):
    db = get_db()
    email = data.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")

    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = hashlib.sha256(otp.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)

    await db.registration_email_otps.update_many(
        {"email": email, "used": False},
        {"$set": {"used": True}},
    )
    await db.registration_email_otps.insert_one({
        "email": email,
        "name": data.name.strip(),
        "phone": data.phone,
        "password_hash": hash_password(data.password),
        "otp_hash": otp_hash,
        "used": False,
        "attempts": 0,
        "expires_at": now + timedelta(minutes=10),
        "created_at": now,
    })
    registration_otp(to_email=email, name=data.name.strip(), otp=otp)
    return {"message": "A verification code has been sent to your email."}


@router.post("/register/verify-otp")
async def verify_registration_otp(data: RegisterOtpIn, response: Response):
    db = get_db()
    email = data.email.lower().strip()
    rec = await db.registration_email_otps.find_one({
        "email": email,
        "used": False,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    }, sort=[("created_at", -1)])
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    if rec.get("attempts", 0) >= 5:
        await db.registration_email_otps.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
        raise HTTPException(status_code=400, detail="Too many verification attempts. Please register again.")

    expected = rec.get("otp_hash", "")
    supplied = hashlib.sha256(data.otp.encode("utf-8")).hexdigest()
    if not secrets.compare_digest(supplied, expected):
        await db.registration_email_otps.update_one({"_id": rec["_id"]}, {"$inc": {"attempts": 1}})
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    if await db.users.find_one({"email": email}):
        await db.registration_email_otps.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
        raise HTTPException(status_code=400, detail="Email already registered")

    doc = {
        "email": email,
        "name": rec["name"],
        "phone": rec.get("phone"),
        "password_hash": rec["password_hash"],
        "role": "customer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.users.insert_one(doc)
    await db.registration_email_otps.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    uid = str(res.inserted_id)
    access = create_access_token(uid, email, "customer")
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    await audit_log("user_registered", uid, email, "user", uid)
    doc["_id"] = res.inserted_id
    return _serialize_user(doc)


@router.post("/activate-account")
async def activate_account(data: ActivateAccountIn):
    db = get_db()
    token_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    rec = await db.account_activation_tokens.find_one({
        "token_hash": token_hash,
        "used": False,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired account activation link")

    try:
        user_id = ObjectId(rec["user_id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid account activation link")

    result = await db.users.update_one(
        {"_id": user_id},
        {"$set": {
            "password_hash": hash_password(data.new_password),
            "account_status": "active",
        }},
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=400, detail="Account activation link is invalid")

    await db.account_activation_tokens.update_one(
        {"_id": rec["_id"]},
        {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}},
    )
    return {"success": True}


@router.post("/login")
async def login(data: LoginIn, request: Request, response: Response):
    db = get_db()
    email = data.email.lower().strip()
    ip = request.client.host if request.client else "unknown"
    identifier = f"{ip}:{email}"
    await check_lockout(identifier)
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(data.password, user["password_hash"]):
        await record_failed_login(identifier)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("disabled"):
        raise HTTPException(status_code=403, detail="Account disabled")
    await clear_login_attempts(identifier)
    uid = str(user["_id"])
    access = create_access_token(uid, email, user.get("role", "customer"))
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    await audit_log("user_logged_in", uid, email, "user", uid)
    return _serialize_user(user)


@router.post("/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    clear_auth_cookies(response)
    await audit_log("user_logged_out", user["id"], user["email"])
    return {"success": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user


@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordIn):
    db = get_db()
    email = data.email.lower().strip()
    user = await db.users.find_one({"email": email})

    if user:
        await db.password_reset_tokens.update_many(
            {"user_id": str(user["_id"]), "used": False},
            {"$set": {"used": True}},
        )

        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)

        await db.password_reset_tokens.insert_one({
            "user_id": str(user["_id"]),
            "token_hash": token_hash,
            "used": False,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc),
        })

        otp = f"{secrets.randbelow(1000000):06d}"
        otp_hash = hashlib.sha256(otp.encode("utf-8")).hexdigest()

        await db.password_reset_tokens.update_one(
            {"token_hash": token_hash},
            {"$set": {"otp_hash": otp_hash, "otp_used": False, "otp_attempts": 0}},
        )

        password_reset(
            to_email=email,
            name=user.get("name", ""),
            reset_token=token,
            otp=otp,
        )

    return {"message": "If the email exists, a password reset link has been sent."}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordIn):
    db = get_db()
    token_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    rec = await db.password_reset_tokens.find_one({
        "token_hash": token_hash,
        "used": False,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    if rec.get("otp_used"):
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    if rec.get("otp_attempts", 0) >= 5:
        await db.password_reset_tokens.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
        raise HTTPException(status_code=400, detail="Too many verification attempts. Please request a new reset code.")
    expected_otp = rec.get("otp_hash", "")
    supplied_otp = hashlib.sha256(data.otp.encode("utf-8")).hexdigest()
    if not expected_otp or not secrets.compare_digest(supplied_otp, expected_otp):
        await db.password_reset_tokens.update_one({"_id": rec["_id"]}, {"$inc": {"otp_attempts": 1}})
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    result = await db.users.update_one(
        {"_id": ObjectId(rec["user_id"])},
        {"$set": {"password_hash": hash_password(data.new_password)}},
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")

    await db.password_reset_tokens.update_one(
        {"_id": rec["_id"]},
        {"$set": {"used": True, "otp_used": True}},
    )
    return {"success": True}
