from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from database import get_db
from security import get_current_user, require_admin, audit_log
from services.notifications import notify_user, notify_admins
from services import email as email_svc
from models import SupportTicketIn, SupportTicketReplyIn, SupportTicketUpdateIn, SUPPORT_TICKET_STATUSES, SUPPORT_TICKET_PRIORITIES

router = APIRouter(prefix="/api/support", tags=["support"])


def _serialize(t):
    return {
        "id": str(t["_id"]),
        "ticket_number": t["ticket_number"],
        "customer_id": t["customer_id"],
        "customer_name": t.get("customer_name", ""),
        "customer_email": t.get("customer_email", ""),
        "subject": t["subject"],
        "message": t["message"],
        "status": t.get("status", "open"),
        "priority": t.get("priority", "normal"),
        "created_at": t["created_at"],
        "updated_at": t.get("updated_at", t["created_at"]),
        "replies": t.get("replies", []),
    }


async def _next_number(db):
    r = await db.counters.find_one_and_update(
        {"name": "support_ticket"},
        {"$inc": {"value": 1}},
        upsert=True,
        return_document=True,
    )
    return f"ZT-{int(r.get('value', 1)):06d}"


@router.post("/tickets")
async def create_ticket(data: SupportTicketIn, user=Depends(get_current_user)):
    if user.get("role") != "customer":
        raise HTTPException(status_code=403, detail="Customers only")
    if data.priority not in SUPPORT_TICKET_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    number = await _next_number(db)
    doc = {
        "ticket_number": number,
        "customer_id": user["id"],
        "customer_name": user.get("name", ""),
        "customer_email": user["email"],
        "subject": data.subject.strip(),
        "message": data.message.strip(),
        "status": "open",
        "priority": data.priority,
        "created_at": now,
        "updated_at": now,
        "replies": [],
    }
    res = await db.support_tickets.insert_one(doc)
    await notify_user(user["id"], "Support ticket created", f"Your support ticket {number} has been received. Our team will review it and respond.")
    admin_msg = f"{number} from {user.get('name') or user['email']}: {doc['subject']} ({data.priority} priority)."
    await notify_admins("New support ticket", admin_msg)
    admins = await db.users.find({"role": "admin", "disabled": {"$ne": True}}, {"email": 1}).to_list(1000)
    for a in admins:
        if a.get("email"):
            email_svc.admin_event(to_email=a["email"], event_title="New support ticket", message=admin_msg)
    email_svc.support_ticket_created(
        to_email=user["email"], name=user.get("name", ""), ticket_number=number,
        subject=doc["subject"], priority=data.priority,
    )
    await audit_log("support_ticket_created", user["id"], user["email"], "support_ticket", str(res.inserted_id))
    return _serialize({**doc, "_id": res.inserted_id})


@router.get("/tickets/mine")
async def my_tickets(user=Depends(get_current_user)):
    if user.get("role") != "customer":
        raise HTTPException(status_code=403, detail="Customers only")
    db = get_db()
    items = await db.support_tickets.find({"customer_id": user["id"]}).sort("updated_at", -1).to_list(500)
    return [_serialize(t) for t in items]


@router.get("/tickets/{ticket_id}")
async def get_ticket(ticket_id: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Ticket not found")
    t = await db.support_tickets.find_one({"_id": oid})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if user.get("role") != "admin" and t.get("customer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    return _serialize(t)


@router.post("/tickets/{ticket_id}/replies")
async def reply_ticket(ticket_id: str, data: SupportTicketReplyIn, user=Depends(get_current_user)):
    db = get_db()
    try:
        oid = ObjectId(ticket_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Ticket not found")
    t = await db.support_tickets.find_one({"_id": oid})
    if not t:
        raise HTTPException(status_code=404, detail="Ticket not found")
    if user.get("role") != "admin" and t.get("customer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    now = datetime.now(timezone.utc).isoformat()
    role = "admin" if user.get("role") == "admin" else "customer"
    reply = {"id": f"{user['id']}-{now}", "role": role, "name": user.get("name", ""), "email": user["email"], "message": data.message.strip(), "created_at": now}
    new_status = "in_progress" if role == "admin" else "open"
    await db.support_tickets.update_one({"_id": oid}, {"$push": {"replies": reply}, "$set": {"updated_at": now, "status": new_status}})
    if role == "admin":
        await notify_user(t.get("customer_id"), "Support ticket updated", f"ZEROAXIS Support replied to ticket {t.get('ticket_number')}: {data.message.strip()}")
        if t.get("customer_email"):
            email_svc.support_ticket_reply(
                to_email=t["customer_email"], name=t.get("customer_name", ""),
                ticket_number=t["ticket_number"], message=data.message.strip(),
            )
    else:
        await notify_admins("Customer replied to support ticket", f"{t.get('ticket_number')} from {user.get('name') or user['email']}: {data.message.strip()}")
        admins = await db.users.find({"role": "admin", "disabled": {"$ne": True}}, {"email": 1}).to_list(1000)
        for a in admins:
            if a.get("email"):
                email_svc.admin_event(
                    to_email=a["email"],
                    event_title="Customer replied to support ticket",
                    message=f"Customer {user.get('name') or user['email']} replied to support ticket {t.get('ticket_number')}: {data.message.strip()}",
                )
    await audit_log("support_ticket_reply", user["id"], user["email"], "support_ticket", ticket_id, {"role": role})
    updated = await db.support_tickets.find_one({"_id": oid})
    return _serialize(updated)


@router.get("/admin/tickets")
async def admin_tickets(status: str | None = None, priority: str | None = None, admin=Depends(require_admin)):
    db = get_db()
    q = {}
    if status:
        if status not in SUPPORT_TICKET_STATUSES: raise HTTPException(status_code=400, detail="Invalid status")
        q["status"] = status
    if priority:
        if priority not in SUPPORT_TICKET_PRIORITIES: raise HTTPException(status_code=400, detail="Invalid priority")
        q["priority"] = priority
    items = await db.support_tickets.find(q).sort("updated_at", -1).to_list(1000)
    return [_serialize(t) for t in items]


@router.put("/admin/tickets/{ticket_id}")
async def admin_update_ticket(ticket_id: str, data: SupportTicketUpdateIn, admin=Depends(require_admin)):
    if data.status is not None and data.status not in SUPPORT_TICKET_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if data.priority is not None and data.priority not in SUPPORT_TICKET_PRIORITIES:
        raise HTTPException(status_code=400, detail="Invalid priority")
    if data.reply is not None and not data.reply.strip():
        raise HTTPException(status_code=400, detail="Reply cannot be empty")
    db = get_db()
    try: oid = ObjectId(ticket_id)
    except Exception: raise HTTPException(status_code=404, detail="Ticket not found")
    t = await db.support_tickets.find_one({"_id": oid})
    if not t: raise HTTPException(status_code=404, detail="Ticket not found")
    now = datetime.now(timezone.utc).isoformat()
    updates = {"updated_at": now}
    if data.status is not None: updates["status"] = data.status
    if data.priority is not None: updates["priority"] = data.priority
    if data.reply is not None:
        reply = {"id": f"{admin['id']}-{now}", "role": "admin", "name": admin.get("name", "Admin"), "email": admin["email"], "message": data.reply.strip(), "created_at": now}
        await db.support_tickets.update_one({"_id": oid}, {"$set": updates, "$push": {"replies": reply}})
    else:
        await db.support_tickets.update_one({"_id": oid}, {"$set": updates})
    if data.status is not None or data.priority is not None:
        parts = []
        if data.status is not None: parts.append(f"status: {data.status.replace('_', ' ')}")
        if data.priority is not None: parts.append(f"priority: {data.priority}")
        await notify_user(t.get("customer_id"), "Support ticket changed", f"Ticket {t.get('ticket_number')} was updated ({', '.join(parts)}).")
        if t.get("customer_email"):
            email_svc.support_ticket_status_changed(
                to_email=t["customer_email"], name=t.get("customer_name", ""),
                ticket_number=t["ticket_number"], status=data.status or t.get("status", ""),
                priority=data.priority or t.get("priority", "normal"),
            )
    if data.reply is not None:
        await notify_user(t.get("customer_id"), "Support ticket reply", f"ZEROAXIS Support replied to ticket {t.get('ticket_number')}: {data.reply.strip()}")
        if t.get("customer_email"):
            email_svc.support_ticket_reply(
                to_email=t["customer_email"], name=t.get("customer_name", ""),
                ticket_number=t["ticket_number"], message=data.reply.strip(),
            )
    await audit_log("support_ticket_updated", admin["id"], admin["email"], "support_ticket", ticket_id, {"status": data.status, "priority": data.priority, "replied": bool(data.reply)})
    return _serialize(await db.support_tickets.find_one({"_id": oid}))
