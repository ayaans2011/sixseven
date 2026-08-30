from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from bson import ObjectId
import secrets

from database import get_db
from security import (
    hash_password, verify_password, create_access_token, create_refresh_token,
    set_auth_cookies, clear_auth_cookies, get_current_user,
    check_lockout, record_failed_login, clear_login_attempts, audit_log,
)
from models import RegisterIn, LoginIn, ForgotPasswordIn, ResetPasswordIn

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
async def register(data: RegisterIn, request: Request, response: Response):
    db = get_db()
    email = data.email.lower().strip()
    if await db.users.find_one({"email": email}):
        raise HTTPException(status_code=400, detail="Email already registered")
    doc = {
        "email": email,
        "name": data.name.strip(),
        "phone": data.phone,
        "password_hash": hash_password(data.password),
        "role": "customer",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await db.users.insert_one(doc)
    uid = str(res.inserted_id)
    access = create_access_token(uid, email, "customer")
    refresh = create_refresh_token(uid)
    set_auth_cookies(response, access, refresh)
    await audit_log("user_registered", uid, email, "user", uid)
    doc["_id"] = res.inserted_id
    return _serialize_user(doc)


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
    # Do not disclose existence
    if user:
        token = secrets.token_urlsafe(32)
        await db.password_reset_tokens.insert_one({
            "user_id": str(user["_id"]),
            "token": token,
            "used": False,
            "expires_at": datetime.now(timezone.utc).replace(microsecond=0),
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        # In production: send via email. For now, expose in server logs.
        print(f"[PASSWORD RESET] For {email}: token={token}")
    return {"message": "If the email exists, a reset link has been generated."}


@router.post("/reset-password")
async def reset_password(data: ResetPasswordIn):
    db = get_db()
    rec = await db.password_reset_tokens.find_one({"token": data.token, "used": False})
    if not rec:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    await db.users.update_one(
        {"_id": ObjectId(rec["user_id"])},
        {"$set": {"password_hash": hash_password(data.new_password)}}
    )
    await db.password_reset_tokens.update_one({"_id": rec["_id"]}, {"$set": {"used": True}})
    return {"success": True}
