from datetime import datetime, timezone, timedelta
import hashlib
import secrets
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from pydantic import BaseModel
from database import get_db
from security import require_admin, get_current_user, audit_log, verify_password, verify_totp, hash_password
from models import ContentIn, AdminCustomerCreateIn, AdminCustomerDeleteIn
from services import email as email_svc

router = APIRouter(prefix="/api", tags=["admin_content"])


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
        "account_status": u.get("account_status", "active"),
        "created_at": u.get("created_at"),
    } for u in items]


@router.post("/admin/customers")
async def create_customer(data: AdminCustomerCreateIn, admin=Depends(require_admin)):
    """Create a passwordless customer account and send a one-time password setup link."""
    db = get_db()
    email = str(data.email).lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing and existing.get("role") != "customer":
        raise HTTPException(status_code=409, detail="This email is already assigned to a non-customer account.")
    if existing and existing.get("account_status") != "pending_activation":
        raise HTTPException(status_code=409, detail="A customer account with this email already exists.")

    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if existing:
        uid = str(existing["_id"])
        await db.users.update_one(
            {"_id": existing["_id"], "role": "customer"},
            {"$set": {
                "name": data.name.strip(), "phone": data.phone, "company": data.company,
                "password_hash": hash_password(secrets.token_urlsafe(48)),
                "account_status": "pending_activation", "disabled": False,
                "invited_at": now.isoformat(), "invited_by": admin["id"],
            }},
        )
        await db.account_activation_tokens.update_many(
            {"user_id": uid, "used": False}, {"$set": {"used": True}}
        )
    else:
        result = await db.users.insert_one({
            "email": email,
            "name": data.name.strip(),
            "phone": data.phone,
            "company": data.company,
            "password_hash": hash_password(secrets.token_urlsafe(48)),
            "role": "customer",
            "account_status": "pending_activation",
            "disabled": False,
            "created_at": now.isoformat(),
            "invited_at": now.isoformat(),
            "invited_by": admin["id"],
        })
        uid = str(result.inserted_id)

    await db.account_activation_tokens.insert_one({
        "user_id": uid, "token_hash": token_hash, "used": False,
        "expires_at": now + timedelta(minutes=30), "created_at": now,
        "created_by": admin["id"],
    })
    email_svc.admin_customer_invitation(to_email=email, name=data.name.strip(), activation_token=token)
    await audit_log("customer_invited_by_admin", admin["id"], admin["email"], "user", uid, {"email": email})
    return {"success": True, "customer_id": uid, "account_status": "pending_activation", "invitation_requested": True}


@router.get("/admin/customers/{uid}")
async def get_customer_record(uid: str, admin=Depends(require_admin)):
    """Return the customer profile and linked business, support and payment records."""
    db = get_db()
    try:
        customer = await db.users.find_one({"_id": ObjectId(uid), "role": "customer"})
    except Exception:
        customer = None
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    email = customer.get("email", "")
    order_query = {"$or": [{"customer_id": uid}, {"customer_email": email}]}
    enquiry_query = {"$or": [{"customer_id": uid}, {"email": email}]}
    orders_raw = await db.orders.find(order_query).sort("created_at", -1).to_list(500)
    enquiries_raw = await db.enquiries.find(enquiry_query).sort("created_at", -1).to_list(500)
    order_ids = [str(o["_id"]) for o in orders_raw]
    enquiry_ids = [str(e["_id"]) for e in enquiries_raw]
    order_history = await db.order_status_history.find({"order_id": {"$in": order_ids}}).sort("timestamp", -1).to_list(1000)
    payments = []
    for order in orders_raw:
        rows = await db.payments.find({"order_id": str(order["_id"])}).sort("created_at", -1).to_list(100)
        for p in rows:
            payments.append({
                "id": str(p["_id"]), "order_id": str(order["_id"]),
                "order_number": order.get("order_number"),
                "method": p.get("method"), "reference": p.get("reference"),
                "amount": p.get("amount"), "status": p.get("status"),
                "provider": p.get("provider"), "provider_order_id": p.get("provider_order_id"),
                "order_amount": p.get("order_amount"), "verified_by": p.get("verified_by"),
                "created_at": p.get("created_at"), "verified_at": p.get("verified_at"),
            })
    support = await db.support_tickets.find({"customer_id": uid}).sort("created_at", -1).to_list(300)
    notifications = await db.notifications.find({"user_id": uid}).sort("created_at", -1).to_list(300)
    files = await db.files.find({"parent_id": {"$in": order_ids + enquiry_ids}, "is_deleted": {"$ne": True}}).sort("created_at", -1).to_list(500)
    messages = await db.messages.find({"parent_id": {"$in": order_ids + enquiry_ids}}).sort("created_at", -1).to_list(500)
    audits = await db.audit_logs.find({"target_id": uid}).sort("timestamp", -1).to_list(200)

    profile = {
        "id": uid, "name": customer.get("name"), "email": email,
        "phone": customer.get("phone"), "company": customer.get("company"),
        "address": customer.get("address"), "disabled": customer.get("disabled", False),
        "account_status": customer.get("account_status", "active"),
        "created_at": customer.get("created_at"), "invited_at": customer.get("invited_at"),
        "activated_at": customer.get("activated_at"),
    }
    orders = [{
        "id": str(o["_id"]), "order_number": o.get("order_number"),
        "service_name": o.get("service_name"), "amount": o.get("amount", 0),
        "requirement": o.get("requirement"), "notes": o.get("notes"),
        "payment_status": o.get("payment_status"), "order_status": o.get("order_status"),
        "created_at": o.get("created_at"), "updated_at": o.get("updated_at"),
    } for o in orders_raw]
    enquiries = [{
        "id": str(e["_id"]), "enquiry_number": e.get("enquiry_number"),
        "service_name": e.get("service_name"), "status": e.get("status"),
        "requirement": e.get("requirement"), "message": e.get("message"),
        "created_at": e.get("created_at"), "admin_response": e.get("admin_response"),
    } for e in enquiries_raw]
    support_rows = [{
        "id": str(t["_id"]), "ticket_number": t.get("ticket_number"),
        "subject": t.get("subject"), "message": t.get("message"),
        "status": t.get("status"), "priority": t.get("priority"),
        "replies": t.get("replies", []), "created_at": t.get("created_at"),
        "updated_at": t.get("updated_at"),
    } for t in support]
    file_rows = [{
        "id": str(x["_id"]), "parent_type": x.get("parent_type"),
        "parent_id": x.get("parent_id"), "original_name": x.get("original_name"),
        "size": x.get("size"), "created_at": x.get("created_at"),
    } for x in files]
    message_rows = [{
        "id": str(m["_id"]), "parent_type": m.get("parent_type"),
        "parent_id": m.get("parent_id"), "sender_role": m.get("sender_role"),
        "sender_email": m.get("sender_email"), "body": m.get("body"),
        "created_at": m.get("created_at"),
    } for m in messages]
    notification_rows = [{
        "id": str(n["_id"]), "title": n.get("title"), "body": n.get("body"),
        "read": n.get("read", False), "created_at": n.get("created_at"),
    } for n in notifications]
    audit_rows = [{
        "action": a.get("action"), "actor_email": a.get("actor_email"),
        "metadata": a.get("metadata", {}), "timestamp": a.get("timestamp"),
    } for a in audits]
    await audit_log("customer_record_viewed", admin["id"], admin["email"], "user", uid)
    return {
        "customer": profile, "orders": orders, "payments": payments,
        "order_history": [{
            "order_id": h.get("order_id"), "from_status": h.get("from_status"),
            "to_status": h.get("to_status"), "note": h.get("note"),
            "actor_email": h.get("actor_email"), "timestamp": h.get("timestamp"),
        } for h in order_history],
        "enquiries": enquiries, "support_tickets": support_rows,
        "attachments": file_rows, "messages": message_rows,
        "notifications": notification_rows, "audit_history": audit_rows,
    }


@router.post("/admin/customers/{uid}/delete")
async def delete_customer_account(uid: str, data: AdminCustomerDeleteIn, admin=Depends(require_admin)):
    """Re-authenticate admin with password + current TOTP; deactivate/anonymise profile, retain financial records."""
    db = get_db()
    try:
        admin_doc = await db.users.find_one({"_id": ObjectId(admin["id"]), "role": "admin", "disabled": {"$ne": True}})
        customer = await db.users.find_one({"_id": ObjectId(uid), "role": "customer"})
    except Exception:
        raise HTTPException(status_code=404, detail="Customer not found")
    if not admin_doc or not verify_password(data.admin_password, admin_doc.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Administrator re-authentication failed.")
    if not verify_totp(admin_doc.get("two_factor_secret", ""), data.totp_code):
        raise HTTPException(status_code=401, detail="Authenticator verification failed.")
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    if str(data.confirm_customer_email).lower().strip() != customer.get("email", "").lower().strip():
        raise HTTPException(status_code=400, detail="Customer email confirmation does not match.")

    now = datetime.now(timezone.utc).isoformat()
    deleted_email = f"deleted+{uid}@deleted.zeroaxis.invalid"
    await audit_log(
        "customer_account_deactivated_and_anonymised", admin["id"], admin["email"],
        "user", uid, {"previous_email": customer.get("email"), "financial_records_retained": True},
    )
    await db.users.update_one(
        {"_id": customer["_id"], "role": "customer"},
        {"$set": {
            "email": deleted_email, "name": "Deleted customer", "phone": None,
            "company": None, "address": None, "disabled": True,
            "account_status": "deleted", "password_hash": hash_password(secrets.token_urlsafe(48)),
            "deleted_at": now, "deleted_by": admin["id"],
        }, "$unset": {"two_factor_secret": "", "two_factor_pending_secret": ""}},
    )
    await db.password_reset_tokens.delete_many({"user_id": uid})
    await db.account_activation_tokens.delete_many({"user_id": uid})
    await db.registration_email_otps.delete_many({"email": customer.get("email")})
    await db.notifications.delete_many({"user_id": uid})
    return {"success": True, "account_status": "deleted", "financial_records_retained": True}


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
        "CREATED", "PAYMENT_PENDING", "PAYMENT_SUBMITTED", "PAYMENT_VERIFIED", "WORK_STARTED", "IN_PROGRESS", "READY_FOR_DELIVERY"
    ]}})
    pending_payments = await db.orders.count_documents({"payment_status": {"$in": ["PENDING_VERIFICATION", "PAYMENT_PENDING"]}})
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
