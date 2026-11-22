import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from bson import ObjectId
import secrets
import hashlib
import hmac

from database import get_db
from security import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    set_auth_cookies, clear_auth_cookies, get_current_user,
    check_lockout, record_failed_login, clear_login_attempts, audit_log, get_jwt_secret,
)
from models import RegisterIn, LoginIn, ForgotPasswordIn, ResetPasswordIn, RegisterOtpIn, ActivateAccountIn
from services.email import send_password_reset, send_registration_otp

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _otp_digest(value: str) -> str:
    return hmac.new(get_jwt_secret().encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()



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
async def register(data: RegisterIn, request: Request):
    db = get_db()
    email = data.email.lower().strip()
    if await db.users.find_one({"email": email}, {"_id": 1}):
        raise HTTPException(status_code=400, detail="Email already registered")
    now = datetime.now(timezone.utc)
    recent = await db.registration_email_otps.count_documents({
        "email": email, "created_at": {"$gt": now - timedelta(minutes=15)}
    })
    if recent >= 3:
        raise HTTPException(status_code=429, detail="Too many verification requests. Try again in 15 minutes.")
    otp = f"{secrets.randbelow(1_000_000):06d}"
    await db.registration_email_otps.update_many(
        {"email": email, "used": False}, {"$set": {"used": True}}
    )
    result = await db.registration_email_otps.insert_one({
        "email": email, "name": data.name.strip(), "phone": data.phone,
        "password_hash": await asyncio.to_thread(hash_password, data.password),
        "otp_hash": _otp_digest(otp), "used": False, "attempts": 0,
        "expires_at": now + timedelta(minutes=10), "created_at": now,
    })
    delivered = await send_registration_otp(to_email=email, name=data.name.strip(), otp=otp)
    if not delivered:
        await db.registration_email_otps.update_one(
            {"_id": result.inserted_id, "used": False}, {"$set": {"used": True}}
        )
        raise HTTPException(status_code=503, detail="We couldn't send the verification email. Please try again later.")
    return {"message": "A verification code has been sent to your email."}

@router.post("/register/verify-otp")
async def verify_registration_otp(data: RegisterOtpIn, response: Response):
    db = get_db()
    email = data.email.lower().strip()
    now = datetime.now(timezone.utc)
    rec = await db.registration_email_otps.find_one(
        {"email": email, "used": False, "expires_at": {"$gt": now}},
        sort=[("created_at", -1)],
    )
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")
    if rec.get("attempts", 0) >= 5:
        await db.registration_email_otps.update_one(
            {"_id": rec["_id"], "used": False}, {"$set": {"used": True}}
        )
        raise HTTPException(status_code=429, detail="Too many verification attempts. Please register again.")
    if await db.users.find_one({"email": email}, {"_id": 1}):
        await db.registration_email_otps.update_one(
            {"_id": rec["_id"], "used": False}, {"$set": {"used": True}}
        )
        raise HTTPException(status_code=400, detail="Email already registered")

    consumed = await db.registration_email_otps.update_one(
        {"_id": rec["_id"], "used": False, "attempts": {"$lt": 5},
         "expires_at": {"$gt": now}, "otp_hash": _otp_digest(data.otp)},
        {"$set": {"used": True, "verified_at": now}},
    )
    if consumed.modified_count != 1:
        await db.registration_email_otps.update_one(
            {"_id": rec["_id"], "used": False, "attempts": {"$lt": 5}},
            {"$inc": {"attempts": 1}},
        )
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    doc = {
        "email": email, "name": rec["name"], "phone": rec.get("phone"),
        "password_hash": rec["password_hash"], "role": "customer",
        "created_at": now.isoformat(),
    }
    try:
        res = await db.users.insert_one(doc)
    except Exception as exc:
        from pymongo.errors import DuplicateKeyError
        if isinstance(exc, DuplicateKeyError):
            raise HTTPException(status_code=400, detail="Email already registered")
        raise
    uid = str(res.inserted_id)
    access = create_access_token(uid, email, "customer")
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    await audit_log("user_registered", uid, email, "user", uid)
    doc["_id"] = res.inserted_id
    return {**_serialize_user(doc), "access_token": access}

@router.post("/activate-account")
async def activate_account(data: ActivateAccountIn):
    db = get_db()
    token_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    rec = await db.account_activation_tokens.find_one({"token_hash": token_hash, "used": False, "expires_at": {"$gt": datetime.now(timezone.utc)}})
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired account activation link")
    try:
        user_id = ObjectId(rec["user_id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid account activation link")
    result = await db.users.update_one({"_id": user_id, "role": "customer", "account_status": {"$ne": "deleted"}}, {"$set": {"password_hash": await asyncio.to_thread(hash_password, data.new_password), "account_status": "active", "activated_at": datetime.now(timezone.utc)}})
    if result.matched_count != 1:
        raise HTTPException(status_code=400, detail="Account activation link is invalid")
    await db.account_activation_tokens.update_one({"_id": rec["_id"]}, {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}})
    return {"success": True}


@router.post("/login")
async def login(data: LoginIn, request: Request, response: Response):
    db = get_db()
    email = data.email.lower().strip()
    ip = request.client.host if request.client else "unknown"
    identifier = f"{ip}:{email}"
    await check_lockout(identifier)
    user = await db.users.find_one({"email": email})
    if user and user.get("account_status") == "pending_activation":
        raise HTTPException(status_code=403, detail="Set your password using the invitation email or Forgot Password first.")
    if not user or not await asyncio.to_thread(verify_password, data.password, user.get("password_hash", "")):
        await record_failed_login(identifier)
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if user.get("disabled") or user.get("account_status") == "deleted":
        raise HTTPException(status_code=403, detail="Account disabled")
    if user.get("role") == "admin":
        raise HTTPException(status_code=403, detail="Use the dedicated admin login")
    await clear_login_attempts(identifier)
    uid = str(user["_id"])
    access = create_access_token(uid, email, user.get("role", "customer"))
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    await audit_log("user_logged_in", uid, email, "user", uid)
    return {**_serialize_user(user), "access_token": access}


@router.post("/logout")
async def logout(response: Response, user: dict = Depends(get_current_user)):
    clear_auth_cookies(response)
    await audit_log("user_logged_out", user["id"], user["email"])
    return {"success": True}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return user


@router.delete("/users/me")
async def delete_my_account(response: Response, user: dict = Depends(get_current_user)):
    db = get_db()
    try:
        user_id = ObjectId(user["id"])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid user")
    current = await db.users.find_one({"_id": user_id, "role": "customer"})
    if not current:
        raise HTTPException(status_code=403, detail="Only customer accounts can be deleted here")
    # Remove the login/account and all authentication/recovery material.
    await db.users.delete_one({"_id": user_id})
    await db.password_reset_tokens.delete_many({"user_id": user["id"]})
    await db.account_activation_tokens.delete_many({"user_id": user["id"]})
    await db.registration_email_otps.delete_many({"email": user["email"]})
    clear_auth_cookies(response)
    await audit_log("customer_account_deleted", user["id"], user["email"], "user", user["id"])
    return {"success": True, "message": "Customer account deleted"}

@router.post("/forgot-password")
async def forgot_password(data: ForgotPasswordIn):
    db = get_db()
    email = data.email.lower().strip()
    user = await db.users.find_one({"email": email})
    if user:
        now = datetime.now(timezone.utc)
        recent = await db.password_reset_tokens.count_documents({
            "user_id": str(user["_id"]),
            "created_at": {"$gt": now - timedelta(minutes=15)},
        })
        # Keep the response identical for known and unknown email addresses.
        if recent >= 3:
            return {"message": "If the email exists, a password reset link has been sent."}
        await db.password_reset_tokens.update_many({"user_id": str(user["_id"]), "used": False}, {"$set": {"used": True}})
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=30)
        await db.password_reset_tokens.insert_one({"user_id": str(user["_id"]), "token_hash": token_hash, "used": False, "expires_at": expires_at, "created_at": datetime.now(timezone.utc)})
        otp = f"{secrets.randbelow(1000000):06d}"
        otp_hash = _otp_digest(otp)
        await db.password_reset_tokens.update_one({"token_hash": token_hash}, {"$set": {"otp_hash": otp_hash, "otp_used": False, "otp_attempts": 0}})
        delivered = await send_password_reset(to_email=email, name=user.get("name", ""), reset_token=token, otp=otp)
        if not delivered:
            await db.password_reset_tokens.update_one(
                {"token_hash": token_hash, "used": False}, {"$set": {"used": True}}
            )
    return {"message": "If the email exists, a password reset link has been sent."}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordIn):
    db = get_db()
    token_hash = hashlib.sha256(data.token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    rec = await db.password_reset_tokens.find_one({
        "token_hash": token_hash, "used": False, "expires_at": {"$gt": now}
    })
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    if rec.get("otp_used") or rec.get("otp_attempts", 0) >= 5:
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    consumed = await db.password_reset_tokens.update_one(
        {"_id": rec["_id"], "used": False, "otp_used": False,
         "otp_attempts": {"$lt": 5}, "expires_at": {"$gt": now},
         "otp_hash": _otp_digest(data.otp)},
        {"$set": {"used": True, "otp_used": True, "used_at": now}},
    )
    if consumed.modified_count != 1:
        await db.password_reset_tokens.update_one(
            {"_id": rec["_id"], "used": False, "otp_used": False,
             "otp_attempts": {"$lt": 5}},
            {"$inc": {"otp_attempts": 1}},
        )
        raise HTTPException(status_code=400, detail="Invalid or expired verification code")

    try:
        user_id = ObjectId(rec["user_id"])
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    result = await db.users.update_one(
        {"_id": user_id, "role": "customer", "account_status": {"$ne": "deleted"}},
        {"$set": {
            "password_hash": await asyncio.to_thread(hash_password, data.new_password),
            "account_status": "active", "activated_at": now,
        }},
    )
    if result.matched_count != 1:
        raise HTTPException(status_code=400, detail="Invalid or expired reset link")
    return {"success": True}
