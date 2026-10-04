from datetime import datetime, timezone
from io import StringIO
import csv
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import Response, StreamingResponse
from bson import ObjectId

from database import get_db
from security import get_current_user, require_admin, audit_log
from models import OrderIn, OrderStatusUpdate, PaymentSubmitIn, PaymentVerifyIn, ORDER_STATUSES
from counters import generate_order_number
from services import email as email_svc
from services.notifications import notify_user, notify_admins
from services.invoice import generate_invoice_pdf

router = APIRouter(prefix="/api/orders", tags=["orders"])


def _serialize(o: dict) -> dict:
    return {
        "id": str(o["_id"]),
        "order_number": o.get("order_number"),
        "tracking_number": o.get("tracking_number"),
        "customer_id": o.get("customer_id"),
        "customer_name": o.get("customer_name"),
        "customer_email": o.get("customer_email"),
        "service_id": o.get("service_id"),
        "service_name": o.get("service_name"),
        "amount": o.get("amount", 0),
        "requirement": o.get("requirement"),
        "notes": o.get("notes"),
        "payment_status": o.get("payment_status", "UNPAID"),
        "order_status": o.get("order_status", "CREATED"),
        "created_at": o.get("created_at"),
        "updated_at": o.get("updated_at"),
    }


async def _add_status_history(db, order_id: str, from_status: str, to_status: str,
                              actor_id: str, actor_email: str, note: str = ""):
    await db.order_status_history.insert_one({
        "order_id": order_id,
        "from_status": from_status,
        "to_status": to_status,
        "actor_id": actor_id,
        "actor_email": actor_email,
        "note": note,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@router.post("")
async def create_order(data: OrderIn, user=Depends(get_current_user)):
    db = get_db()
    try:
        service = await db.services.find_one({"_id": ObjectId(data.service_id), "active": True})
    except Exception:
        raise HTTPException(status_code=404, detail="Service not found")
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    number = await generate_order_number()
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "order_number": number,
        "tracking_number": number,  # same public tracking id
        "customer_id": user["id"],
        "customer_name": user.get("name", ""),
        "customer_email": user["email"],
        "service_id": data.service_id,
        "service_name": service["name"],
        "amount": float(service.get("price", 0)),
        "requirement": data.requirement,
        "notes": data.notes or "",
        "payment_status": "UNPAID",
        "order_status": "CREATED",
        "created_at": now,
        "updated_at": now,
    }
    res = await db.orders.insert_one(doc)
    doc["_id"] = res.inserted_id
    await _add_status_history(db, str(res.inserted_id), "", "CREATED", user["id"], user["email"], "Order created")
    await notify_user(user["id"], "Order created", f"Your order {number} has been created for {service['name']}. Please complete payment to proceed.", now=now)
    await notify_admins("New order received", f"Order {number} was created by {user.get('name') or user['email']} for {service['name']} (₹{float(service.get('price', 0)):,.0f}).", now=now)
    await audit_log("order_created", user["id"], user["email"], "order", str(res.inserted_id), {"number": number})
    email_svc.order_created(
        to_email=user["email"], name=user.get("name", ""),
        order_number=number, service_name=service["name"], amount=float(service.get("price", 0)),
    )
    return _serialize(doc)


@router.get("/mine")
async def my_orders(user=Depends(get_current_user)):
    db = get_db()
    items = await db.orders.find({"customer_id": user["id"]}).sort("created_at", -1).to_list(500)
    return [_serialize(o) for o in items]


@router.get("/track/{tracking_number}")
async def track_public(tracking_number: str):
    """Public: track by tracking number returns limited info."""
    db = get_db()
    o = await db.orders.find_one({"tracking_number": tracking_number})
    if not o:
        raise HTTPException(status_code=404, detail="Order not found")
    history = await db.order_status_history.find({"order_id": str(o["_id"])}).sort("timestamp", 1).to_list(200)
    return {
        "tracking_number": o["tracking_number"],
        "order_number": o["order_number"],
        "service_name": o.get("service_name"),
        "order_status": o.get("order_status"),
        "payment_status": o.get("payment_status"),
        "created_at": o.get("created_at"),
        "updated_at": o.get("updated_at"),
        "history": [{
            "from_status": h.get("from_status"),
            "to_status": h.get("to_status"),
            "note": h.get("note"),
            "timestamp": h.get("timestamp"),
        } for h in history],
    }


@router.get("/{oid}")
async def get_order(oid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        o = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] != "admin" and o.get("customer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    history = await db.order_status_history.find({"order_id": oid}).sort("timestamp", 1).to_list(200)
    payments = await db.payments.find({"order_id": oid}).sort("created_at", -1).to_list(50)
    return {
        **_serialize(o),
        "history": [{
            "from_status": h.get("from_status"),
            "to_status": h.get("to_status"),
            "note": h.get("note"),
            "actor_email": h.get("actor_email"),
            "timestamp": h.get("timestamp"),
        } for h in history],
        "payments": [{
            "id": str(p["_id"]),
            "method": p.get("method"),
            "reference": p.get("reference"),
            "amount": p.get("amount"),
            "status": p.get("status"),
            "note": p.get("note"),
            "created_at": p.get("created_at"),
            "verified_by": p.get("verified_by"),
            "verified_at": p.get("verified_at"),
        } for p in payments],
    }


# Customer: submit payment info
@router.post("/{oid}/payment")
async def submit_payment(oid: str, data: PaymentSubmitIn, user=Depends(get_current_user)):
    db = get_db()
    try:
        o = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not o or o.get("customer_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Not found")
    if o.get("payment_status") == "PAYMENT_VERIFIED":
        raise HTTPException(status_code=400, detail="Payment already verified")
    now = datetime.now(timezone.utc).isoformat()
    payment_doc = {
        "order_id": oid,
        "customer_id": user["id"],
        "method": data.method,
        "reference": data.reference,
        "amount": data.amount,
        "note": data.note or "",
        "status": "PENDING_VERIFICATION",
        "created_at": now,
    }
    await db.payments.insert_one(payment_doc)
    prev_pay = o.get("payment_status", "UNPAID")
    prev_ord = o.get("order_status", "CREATED")
    await db.orders.update_one({"_id": o["_id"]}, {"$set": {
        "payment_status": "PENDING_VERIFICATION",
        "order_status": "PAYMENT_SUBMITTED",
        "updated_at": now,
    }})
    await _add_status_history(db, oid, prev_ord, "PAYMENT_SUBMITTED", user["id"], user["email"], f"Payment via {data.method}, ref {data.reference}")
    await notify_user(user["id"], "Payment submitted", f"Payment for order {o['order_number']} was submitted and is awaiting verification.", now=now)
    await notify_admins("Payment awaiting verification", f"Payment submitted for order {o['order_number']} by {user.get('name') or user['email']}. Reference: {data.reference}.", now=now)
    await audit_log("payment_submitted", user["id"], user["email"], "order", oid, {"prev": prev_pay})
    email_svc.payment_submitted(
        to_email=user["email"], name=user.get("name", ""),
        order_number=o["order_number"], amount=float(data.amount), reference=data.reference,
    )
    return {"success": True}


# Admin: verify or reject payment
@router.post("/{oid}/payment/verify")
async def verify_payment(oid: str, data: PaymentVerifyIn, admin=Depends(require_admin)):
    db = get_db()
    try:
        o = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    payment = await db.payments.find_one({"order_id": oid, "status": "PENDING_VERIFICATION"})
    if not payment:
        raise HTTPException(status_code=400, detail="No pending payment to verify")
    now = datetime.now(timezone.utc).isoformat()
    prev_pay = o.get("payment_status")
    prev_ord = o.get("order_status")
    if data.action == "verify":
        new_pay = "PAYMENT_VERIFIED"
        new_ord = "PAYMENT_VERIFIED"
        pay_status = "PAYMENT_VERIFIED"
        title = "Payment verified"
        body = f"Payment for order {o['order_number']} has been verified. Work will start soon."
    elif data.action == "reject":
        new_pay = "PAYMENT_REJECTED"
        new_ord = "CREATED"
        pay_status = "PAYMENT_REJECTED"
        title = "Payment rejected"
        body = f"Payment for order {o['order_number']} was rejected. {data.note or ''}"
    else:
        raise HTTPException(status_code=400, detail="Invalid action")

    await db.payments.update_one({"_id": payment["_id"]}, {"$set": {
        "status": pay_status,
        "verified_by": admin["email"],
        "verified_at": now,
        "verification_note": data.note or "",
    }})
    await db.orders.update_one({"_id": o["_id"]}, {"$set": {
        "payment_status": new_pay,
        "order_status": new_ord,
        "updated_at": now,
    }})
    await _add_status_history(db, oid, prev_ord, new_ord, admin["id"], admin["email"], f"Payment {data.action} - {data.note or ''}")
    if o.get("customer_id"):
        await db.notifications.insert_one({
            "user_id": o["customer_id"],
            "title": title,
            "body": body,
            "read": False,
            "created_at": now,
        })
    await audit_log(f"payment_{data.action}", admin["id"], admin["email"], "order", oid,
                    {"prev_payment": prev_pay, "new_payment": new_pay, "note": data.note})
    to_email = o.get("customer_email")
    if to_email:
        if data.action == "verify":
            email_svc.payment_verified(to_email=to_email, name=o.get("customer_name", ""),
                                        order_number=o["order_number"], amount=float(o.get("amount", 0)))
        else:
            email_svc.payment_rejected(to_email=to_email, name=o.get("customer_name", ""),
                                        order_number=o["order_number"], note=data.note or "")
    return {"success": True}


# Admin: update order status
@router.post("/{oid}/status")
async def update_status(oid: str, data: OrderStatusUpdate, admin=Depends(require_admin)):
    if data.order_status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    db = get_db()
    try:
        o = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    prev = o.get("order_status")
    now = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"_id": o["_id"]}, {"$set": {
        "order_status": data.order_status,
        "updated_at": now,
    }})
    await _add_status_history(db, oid, prev, data.order_status, admin["id"], admin["email"], data.note or "")
    if o.get("customer_id"):
        await db.notifications.insert_one({
            "user_id": o["customer_id"],
            "title": "Order status updated",
            "body": f"Order {o['order_number']} is now {data.order_status.replace('_', ' ').title()}.",
            "read": False,
            "created_at": now,
        })
    await audit_log("order_status_changed", admin["id"], admin["email"], "order", oid,
                    {"from": prev, "to": data.order_status})
    if o.get("customer_email"):
        email_svc.status_changed(
            to_email=o["customer_email"], name=o.get("customer_name", ""),
            order_number=o["order_number"], new_status=data.order_status, note=data.note or "",
        )
    return {"success": True}


# Admin: search / filter / export list of orders
@router.get("/admin/all")
async def admin_list(
    admin=Depends(require_admin),
    status: str | None = Query(None),
    payment_status: str | None = Query(None),
    q: str | None = Query(None, description="Search by order/tracking number, customer name or email"),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
):
    db = get_db()
    query: dict = {}
    if status:
        query["order_status"] = status
    if payment_status:
        query["payment_status"] = payment_status
    if date_from:
        query.setdefault("created_at", {})["$gte"] = date_from
    if date_to:
        query.setdefault("created_at", {})["$lte"] = date_to
    if q:
        rx = {"$regex": q, "$options": "i"}
        query["$or"] = [
            {"order_number": rx}, {"tracking_number": rx},
            {"customer_name": rx}, {"customer_email": rx},
            {"service_name": rx},
        ]
    items = await db.orders.find(query).sort("created_at", -1).to_list(limit)
    return [_serialize(o) for o in items]


@router.get("/admin/export.csv")
async def admin_export_csv(
    admin=Depends(require_admin),
    status: str | None = Query(None),
    payment_status: str | None = Query(None),
    q: str | None = Query(None),
    date_from: str | None = Query(None),
    date_to: str | None = Query(None),
):
    db = get_db()
    query: dict = {}
    if status:
        query["order_status"] = status
    if payment_status:
        query["payment_status"] = payment_status
    if date_from:
        query.setdefault("created_at", {})["$gte"] = date_from
    if date_to:
        query.setdefault("created_at", {})["$lte"] = date_to
    if q:
        rx = {"$regex": q, "$options": "i"}
        query["$or"] = [
            {"order_number": rx}, {"tracking_number": rx},
            {"customer_name": rx}, {"customer_email": rx},
            {"service_name": rx},
        ]
    items = await db.orders.find(query).sort("created_at", -1).to_list(5000)
    buf = StringIO()
    w = csv.writer(buf)
    w.writerow(["Order #", "Tracking #", "Customer", "Email", "Service", "Amount",
                "Payment Status", "Order Status", "Created", "Updated"])
    for o in items:
        w.writerow([
            o.get("order_number", ""), o.get("tracking_number", ""),
            o.get("customer_name", ""), o.get("customer_email", ""),
            o.get("service_name", ""), o.get("amount", 0),
            o.get("payment_status", ""), o.get("order_status", ""),
            o.get("created_at", ""), o.get("updated_at", ""),
        ])
    csv_bytes = buf.getvalue().encode("utf-8")
    filename = f"zeroaxis-orders-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
    return Response(
        content=csv_bytes,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Invoice PDF — customer (own order) or admin. Requires payment verified.
@router.get("/{oid}/invoice.pdf")
async def invoice_pdf(oid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        o = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not o:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] != "admin" and o.get("customer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    if o.get("payment_status") != "PAYMENT_VERIFIED":
        raise HTTPException(status_code=400, detail="Invoice available only after payment verification")

    customer = None
    if o.get("customer_id"):
        try:
            customer = await db.users.find_one({"_id": ObjectId(o["customer_id"])})
        except Exception:
            customer = None
    customer = customer or {"name": o.get("customer_name"), "email": o.get("customer_email")}

    content_items = await db.content.find({}).to_list(50)
    content = {c["key"]: c.get("value", {}) for c in content_items}

    pdf_bytes = generate_invoice_pdf(order=o, customer=customer, content=content)
    filename = f"invoice-{o.get('order_number','order')}.pdf"
    await audit_log("invoice_downloaded", user["id"], user["email"], "order", oid)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
