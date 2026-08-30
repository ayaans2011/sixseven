"""Simple message threads attached to an order or enquiry.

Customer <-> Admin conversation. Ownership enforced via parent record.
"""
from datetime import datetime, timezone
from typing import Literal
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from database import get_db
from security import get_current_user, audit_log

router = APIRouter(prefix="/api/messages", tags=["messages"])


class MessagePost(BaseModel):
    parent_type: Literal["order", "enquiry"]
    parent_id: str
    body: str


async def _load_parent(db, parent_type: str, parent_id: str) -> dict:
    coll = db.orders if parent_type == "order" else db.enquiries
    try:
        doc = await coll.find_one({"_id": ObjectId(parent_id)})
    except Exception:
        raise HTTPException(status_code=404, detail="Parent not found")
    if not doc:
        raise HTTPException(status_code=404, detail="Parent not found")
    return doc


def _can_access(user: dict, parent: dict) -> bool:
    if user["role"] == "admin":
        return True
    return parent.get("customer_id") == user["id"]


@router.get("")
async def list_messages(parent_type: str = Query(...), parent_id: str = Query(...),
                        user=Depends(get_current_user)):
    if parent_type not in ("order", "enquiry"):
        raise HTTPException(status_code=400, detail="Invalid parent_type")
    db = get_db()
    parent = await _load_parent(db, parent_type, parent_id)
    if not _can_access(user, parent):
        raise HTTPException(status_code=403, detail="Forbidden")
    items = await db.messages.find(
        {"parent_type": parent_type, "parent_id": parent_id}
    ).sort("created_at", 1).to_list(500)
    # Mark other-party's messages as read for this user
    other_role = "customer" if user["role"] == "admin" else "admin"
    await db.messages.update_many(
        {"parent_type": parent_type, "parent_id": parent_id,
         "sender_role": other_role, "read": False},
        {"$set": {"read": True}}
    )
    return [{
        "id": str(m["_id"]),
        "sender_role": m["sender_role"],
        "sender_email": m["sender_email"],
        "sender_name": m.get("sender_name"),
        "body": m["body"],
        "read": m.get("read", False),
        "created_at": m["created_at"],
    } for m in items]


@router.post("")
async def post_message(data: MessagePost, user=Depends(get_current_user)):
    if data.parent_type not in ("order", "enquiry"):
        raise HTTPException(status_code=400, detail="Invalid parent_type")
    body = (data.body or "").strip()
    if not body:
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    if len(body) > 4000:
        raise HTTPException(status_code=400, detail="Message too long (max 4000 chars)")
    db = get_db()
    parent = await _load_parent(db, data.parent_type, data.parent_id)
    if not _can_access(user, parent):
        raise HTTPException(status_code=403, detail="Forbidden")
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "parent_type": data.parent_type,
        "parent_id": data.parent_id,
        "sender_id": user["id"],
        "sender_email": user["email"],
        "sender_name": user.get("name"),
        "sender_role": user["role"],
        "body": body,
        "read": False,
        "created_at": now,
    }
    res = await db.messages.insert_one(doc)

    # Notify the other party in-app
    if user["role"] == "admin" and parent.get("customer_id"):
        await db.notifications.insert_one({
            "user_id": parent["customer_id"],
            "title": "New message from ZEROAXIS",
            "body": f"You have a new message on {data.parent_type} {parent.get('order_number') or parent.get('enquiry_number','')}.",
            "read": False,
            "created_at": now,
        })
    await audit_log("message_posted", user["id"], user["email"], data.parent_type, data.parent_id,
                    {"message_id": str(res.inserted_id)})
    return {"id": str(res.inserted_id), "success": True}


@router.get("/unread-count")
async def unread_count(user=Depends(get_current_user)):
    """Return number of messages addressed to this user across all their threads."""
    db = get_db()
    other_role = "customer" if user["role"] == "admin" else "admin"
    if user["role"] == "admin":
        # For admin, count all unread messages from customers globally
        count = await db.messages.count_documents({"sender_role": "customer", "read": False})
    else:
        # Get user's orders + enquiries ids
        orders = await db.orders.find({"customer_id": user["id"]}, {"_id": 1}).to_list(500)
        enquiries = await db.enquiries.find({"customer_id": user["id"]}, {"_id": 1}).to_list(500)
        oids = [str(o["_id"]) for o in orders]
        eids = [str(e["_id"]) for e in enquiries]
        q = {"sender_role": other_role, "read": False, "$or": [
            {"parent_type": "order", "parent_id": {"$in": oids}},
            {"parent_type": "enquiry", "parent_id": {"$in": eids}},
        ]}
        count = await db.messages.count_documents(q)
    return {"unread": count}
