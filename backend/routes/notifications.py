from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from database import get_db
from security import get_current_user, require_admin, audit_log
from models import NotificationIn, ProfileUpdateIn

router = APIRouter(prefix="/api", tags=["users_notifications"])


# ---------- Notifications ----------
@router.get("/notifications")
async def my_notifications(user=Depends(get_current_user)):
    db = get_db()
    items = await db.notifications.find({"user_id": user["id"]}).sort("created_at", -1).to_list(200)
    return [{
        "id": str(n["_id"]),
        "title": n["title"],
        "body": n["body"],
        "read": n.get("read", False),
        "created_at": n.get("created_at"),
    } for n in items]


@router.post("/notifications/{nid}/read")
async def mark_read(nid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        oid = ObjectId(nid)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    n = await db.notifications.find_one({"_id": oid})
    if not n or n.get("user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Not found")
    await db.notifications.update_one({"_id": oid}, {"$set": {"read": True}})
    return {"success": True}


@router.post("/admin/notifications")
async def send_notification(data: NotificationIn, admin=Depends(require_admin)):
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    if data.user_id:
        await db.notifications.insert_one({
            "user_id": data.user_id, "title": data.title, "body": data.body,
            "read": False, "created_at": now,
        })
    else:
        # broadcast to all customers
        users = await db.users.find({"role": "customer"}, {"_id": 1}).to_list(10000)
        docs = [{"user_id": str(u["_id"]), "title": data.title, "body": data.body,
                 "read": False, "created_at": now} for u in users]
        if docs:
            await db.notifications.insert_many(docs)
    await audit_log("notification_sent", admin["id"], admin["email"], "notification", data.user_id or "broadcast")
    return {"success": True}


# ---------- Profile ----------
@router.put("/users/me")
async def update_profile(data: ProfileUpdateIn, user=Depends(get_current_user)):
    db = get_db()
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update:
        return user
    await db.users.update_one({"_id": ObjectId(user["id"])}, {"$set": update})
    u = await db.users.find_one({"_id": ObjectId(user["id"])})
    u["id"] = str(u["_id"])
    u.pop("_id", None); u.pop("password_hash", None)
    return u
