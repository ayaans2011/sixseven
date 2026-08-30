from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from pydantic import BaseModel
from database import get_db
from security import require_admin, get_current_user, audit_log
from models import ContentIn
from services import email as email_svc

router = APIRouter(prefix="/api", tags=["admin_content"])


class QRUploadIn(BaseModel):
    data_url: str  # data:image/png;base64,...
    label: str | None = ""


def _validate_data_url(data_url: str):
    if not data_url.startswith("data:image/"):
        raise HTTPException(status_code=400, detail="Must be an image data URL (data:image/...;base64,...)")
    # Size guard ~ 2MB base64
    if len(data_url) > 3_000_000:
        raise HTTPException(status_code=400, detail="Image too large (max ~2MB)")


# ---------- Website Content ----------
@router.get("/content")
async def list_content():
    db = get_db()
    items = await db.content.find({}).to_list(200)
    return {c["key"]: c.get("value", {}) for c in items}


@router.get("/content/{key}")
async def get_content(key: str):
    db = get_db()
    c = await db.content.find_one({"key": key})
    if not c:
        return {"key": key, "value": {}}
    return {"key": key, "value": c.get("value", {})}


@router.put("/admin/content")
async def upsert_content(data: ContentIn, admin=Depends(require_admin)):
    db = get_db()
    await db.content.update_one(
        {"key": data.key},
        {"$set": {"key": data.key, "value": data.value, "updated_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True,
    )
    await audit_log("content_updated", admin["id"], admin["email"], "content", data.key)
    return {"success": True}


# ---------- Admin: customers ----------
@router.get("/admin/customers")
async def list_customers(admin=Depends(require_admin)):
    db = get_db()
    items = await db.users.find({"role": "customer"}).sort("created_at", -1).to_list(1000)
    return [{
        "id": str(u["_id"]),
        "name": u.get("name"),
        "email": u["email"],
        "phone": u.get("phone"),
        "company": u.get("company"),
        "disabled": u.get("disabled", False),
        "has_qr": bool(u.get("payment_qr")),
        "payment_qr_label": u.get("payment_qr_label", ""),
        "created_at": u.get("created_at"),
    } for u in items]


@router.put("/admin/customers/{uid}/qr")
async def set_customer_qr(uid: str, data: QRUploadIn, admin=Depends(require_admin)):
    _validate_data_url(data.data_url)
    db = get_db()
    try:
        u = await db.users.find_one({"_id": ObjectId(uid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not u or u.get("role") != "customer":
        raise HTTPException(status_code=404, detail="Not found")
    await db.users.update_one({"_id": u["_id"]}, {"$set": {
        "payment_qr": data.data_url,
        "payment_qr_label": data.label or "",
    }})
    await audit_log("customer_qr_set", admin["id"], admin["email"], "user", uid)
    return {"success": True}


@router.delete("/admin/customers/{uid}/qr")
async def clear_customer_qr(uid: str, admin=Depends(require_admin)):
    db = get_db()
    try:
        await db.users.update_one({"_id": ObjectId(uid)}, {"$unset": {"payment_qr": "", "payment_qr_label": ""}})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    await audit_log("customer_qr_cleared", admin["id"], admin["email"], "user", uid)
    return {"success": True}


@router.get("/admin/customers/{uid}/qr")
async def get_customer_qr_admin(uid: str, admin=Depends(require_admin)):
    db = get_db()
    try:
        u = await db.users.find_one({"_id": ObjectId(uid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not u:
        raise HTTPException(status_code=404, detail="Not found")
    return {"data_url": u.get("payment_qr"), "label": u.get("payment_qr_label", "")}


@router.get("/orders/{oid}/qr")
async def get_order_qr(oid: str, user=Depends(get_current_user)):
    """Returns the QR image for an order. Prefers order-specific QR, falls back to customer's default QR."""
    db = get_db()
    try:
        o = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] != "admin" and o.get("customer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    data_url = o.get("payment_qr")
    label = o.get("payment_qr_label", "")
    if not data_url and o.get("customer_id"):
        try:
            cu = await db.users.find_one({"_id": ObjectId(o["customer_id"])})
            if cu:
                data_url = cu.get("payment_qr")
                label = cu.get("payment_qr_label", label)
        except Exception:
            pass
    return {"data_url": data_url, "label": label}


@router.put("/admin/orders/{oid}/qr")
async def set_order_qr(oid: str, data: QRUploadIn, admin=Depends(require_admin)):
    _validate_data_url(data.data_url)
    db = get_db()
    try:
        o = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    await db.orders.update_one({"_id": o["_id"]}, {"$set": {
        "payment_qr": data.data_url,
        "payment_qr_label": data.label or "",
    }})
    await audit_log("order_qr_set", admin["id"], admin["email"], "order", oid)
    return {"success": True}


@router.delete("/admin/orders/{oid}/qr")
async def clear_order_qr(oid: str, admin=Depends(require_admin)):
    db = get_db()
    try:
        await db.orders.update_one({"_id": ObjectId(oid)}, {"$unset": {"payment_qr": "", "payment_qr_label": ""}})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    await audit_log("order_qr_cleared", admin["id"], admin["email"], "order", oid)
    return {"success": True}


@router.post("/admin/customers/{uid}/toggle")
async def toggle_customer(uid: str, admin=Depends(require_admin)):
    db = get_db()
    try:
        u = await db.users.find_one({"_id": ObjectId(uid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not u or u.get("role") != "customer":
        raise HTTPException(status_code=404, detail="Not found")
    new_state = not u.get("disabled", False)
    await db.users.update_one({"_id": u["_id"]}, {"$set": {"disabled": new_state}})
    await audit_log("customer_toggled", admin["id"], admin["email"], "user", uid, {"disabled": new_state})
    return {"success": True, "disabled": new_state}


# ---------- Admin: dashboard stats ----------
@router.get("/admin/stats")
async def stats(admin=Depends(require_admin)):
    db = get_db()
    total_customers = await db.users.count_documents({"role": "customer"})
    new_enquiries = await db.enquiries.count_documents({"status": "new"})
    active_orders = await db.orders.count_documents({"order_status": {"$in": [
        "CREATED", "PAYMENT_SUBMITTED", "PAYMENT_VERIFIED", "WORK_STARTED", "IN_PROGRESS", "READY_FOR_DELIVERY"
    ]}})
    pending_payments = await db.orders.count_documents({"payment_status": "PENDING_VERIFICATION"})
    verified_payments = await db.orders.count_documents({"payment_status": "PAYMENT_VERIFIED"})
    completed_orders = await db.orders.count_documents({"order_status": "COMPLETED"})
    total_orders = await db.orders.count_documents({})
    return {
        "total_customers": total_customers,
        "new_enquiries": new_enquiries,
        "active_orders": active_orders,
        "pending_payments": pending_payments,
        "verified_payments": verified_payments,
        "completed_orders": completed_orders,
        "total_orders": total_orders,
    }


# ---------- Audit logs ----------
@router.get("/admin/audit-logs")
async def audit_logs(admin=Depends(require_admin), limit: int = 200):
    db = get_db()
    items = await db.audit_logs.find({}).sort("timestamp", -1).to_list(limit)
    return [{
        "id": str(a["_id"]),
        "action": a.get("action"),
        "actor_email": a.get("actor_email"),
        "target_type": a.get("target_type"),
        "target_id": a.get("target_id"),
        "metadata": a.get("metadata", {}),
        "timestamp": a.get("timestamp"),
    } for a in items]


# ---------- Bulk payment reminders ----------
class BulkRemindersOut(BaseModel):
    sent: int
    skipped: int
    matched: int


@router.get("/admin/payments/pending")
async def pending_payments(admin=Depends(require_admin)):
    """List orders that need a payment nudge: UNPAID or PAYMENT_REJECTED (not verified)."""
    db = get_db()
    q = {"payment_status": {"$in": ["UNPAID", "PAYMENT_REJECTED"]}}
    items = await db.orders.find(q).sort("created_at", -1).to_list(2000)
    return [{
        "id": str(o["_id"]),
        "order_number": o.get("order_number"),
        "customer_name": o.get("customer_name"),
        "customer_email": o.get("customer_email"),
        "service_name": o.get("service_name"),
        "amount": o.get("amount", 0),
        "payment_status": o.get("payment_status"),
        "created_at": o.get("created_at"),
        "last_reminded_at": o.get("last_reminded_at"),
    } for o in items]


@router.post("/admin/payments/remind-all")
async def remind_all_pending(admin=Depends(require_admin), force: bool = False):
    """Email a payment reminder to every customer with an UNPAID/PAYMENT_REJECTED order.

    Cooldown: skip orders reminded within the last 24h unless `force=true`.
    """
    db = get_db()
    now = datetime.now(timezone.utc)
    cutoff_iso = (now - timedelta(hours=24)).isoformat()
    q = {"payment_status": {"$in": ["UNPAID", "PAYMENT_REJECTED"]}}
    orders = await db.orders.find(q).to_list(2000)
    sent = 0
    skipped = 0
    for o in orders:
        last = o.get("last_reminded_at")
        if not force and last and last > cutoff_iso:
            skipped += 1
            continue
        email = o.get("customer_email")
        if not email:
            skipped += 1
            continue
        # days since created
        try:
            created = datetime.fromisoformat((o.get("created_at") or now.isoformat()).replace("Z", "+00:00"))
            days = max(0, (now - created).days)
        except Exception:
            days = 0
        email_svc.payment_reminder(
            to_email=email, name=o.get("customer_name", ""),
            order_number=o.get("order_number", ""),
            amount=float(o.get("amount", 0) or 0),
            days_since_created=days,
            previously_rejected=(o.get("payment_status") == "PAYMENT_REJECTED"),
        )
        await db.orders.update_one({"_id": o["_id"]}, {"$set": {"last_reminded_at": now.isoformat()}})
        # In-app notification too
        if o.get("customer_id"):
            await db.notifications.insert_one({
                "user_id": o["customer_id"],
                "title": "Payment reminder",
                "body": f"Order {o.get('order_number','')} is awaiting payment. Please complete it from your dashboard.",
                "read": False,
                "created_at": now.isoformat(),
            })
        sent += 1
    await audit_log("payment_reminders_sent", admin["id"], admin["email"], "orders", "bulk",
                    {"sent": sent, "skipped": skipped, "matched": len(orders), "force": force})
    return BulkRemindersOut(sent=sent, skipped=skipped, matched=len(orders))


@router.post("/admin/payments/{oid}/remind")
async def remind_one(oid: str, admin=Depends(require_admin)):
    """Send a payment reminder for a single order (bypasses cooldown)."""
    db = get_db()
    try:
        o = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    if o.get("payment_status") not in ("UNPAID", "PAYMENT_REJECTED"):
        raise HTTPException(status_code=400, detail="Order does not need a reminder")
    email = o.get("customer_email")
    if not email:
        raise HTTPException(status_code=400, detail="No customer email on order")
    now = datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat((o.get("created_at") or now.isoformat()).replace("Z", "+00:00"))
        days = max(0, (now - created).days)
    except Exception:
        days = 0
    email_svc.payment_reminder(
        to_email=email, name=o.get("customer_name", ""),
        order_number=o.get("order_number", ""),
        amount=float(o.get("amount", 0) or 0),
        days_since_created=days,
        previously_rejected=(o.get("payment_status") == "PAYMENT_REJECTED"),
    )
    await db.orders.update_one({"_id": o["_id"]}, {"$set": {"last_reminded_at": now.isoformat()}})
    await audit_log("payment_reminder_sent", admin["id"], admin["email"], "order", oid)
    return {"success": True}
