from datetime import datetime, timezone
from io import StringIO
import csv
import os
import hmac
import hashlib
import httpx
import logging
import secrets
from pydantic import EmailStr
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import Response, StreamingResponse
from bson import ObjectId

from database import get_db
from security import get_current_user, require_admin, audit_log
from models import OrderIn, OrderStatusUpdate, ORDER_STATUSES
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
    tracking_token = secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "order_number": number,
        "tracking_number": tracking_token,
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
    admin_msg = f"Order {number} was created by {user.get('name') or user['email']} for {service['name']} (₹{float(service.get('price', 0)):,.0f})."
    await notify_admins("New order received", admin_msg, now=now)
    admins = await db.users.find({"role": "admin", "disabled": {"$ne": True}}, {"email": 1}).to_list(1000)
    for a in admins:
        if a.get("email"): email_svc.admin_event(to_email=a["email"], event_title="New order received", message=admin_msg)
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
async def track_public(tracking_number: str, email: EmailStr = Query(...)):
    """Public tracking requires both the private tracking token and order email."""
    db = get_db()
    normalized_email = str(email).lower().strip()
    o = await db.orders.find_one({
        "tracking_number": tracking_number,
        "customer_email": normalized_email,
    })
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



# FamGateway payment integration
FAMGATEWAY_BASE_URL = "https://famgateway.in"
logger = logging.getLogger("zeroaxis.famgateway")

async def _famgateway_request(method: str, path: str, *, params=None, payload=None):
    api_key = os.environ.get("FAMGATEWAY_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Online payments are not configured")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.request(method, FAMGATEWAY_BASE_URL + path,
                headers={"X-Api-Key": api_key, "Accept": "application/json"},
                params=params, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        logger.warning("FamGateway HTTP error: %s", exc.response.status_code)
        raise HTTPException(status_code=502, detail="Payment provider could not process the request")
    except (httpx.HTTPError, ValueError):
        logger.exception("FamGateway request failed")
        raise HTTPException(status_code=502, detail="Could not contact the payment provider")
    if isinstance(data, dict) and data.get("status") == "error":
        raise HTTPException(status_code=502, detail="Payment provider rejected the request")
    return data

def _gateway_data(payload: dict) -> dict:
    value = payload.get("data") if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else (payload if isinstance(payload, dict) else {})

def _amount_matches(actual, expected) -> bool:
    try:
        return round(float(actual), 2) == round(float(expected), 2)
    except (TypeError, ValueError):
        return False

async def _mark_famgateway_paid(db, payment: dict, order: dict, gateway_data: dict):
    now = datetime.now(timezone.utc).isoformat()
    oid = str(order["_id"])
    utr = str(gateway_data.get("utr") or "").strip()
    if not utr:
        raise HTTPException(status_code=409, detail="Verified payment has no UTR")
    duplicate = await db.payments.find_one({"provider": "famgateway", "utr": utr, "order_id": {"$ne": oid}})
    if duplicate:
        raise HTTPException(status_code=409, detail="Transaction reference already used")
    changed = await db.orders.update_one(
        {"_id": order["_id"], "payment_status": {"$ne": "PAYMENT_VERIFIED"}},
        {"$set": {"payment_status": "PAYMENT_VERIFIED", "order_status": "PAYMENT_VERIFIED", "updated_at": now}})
    if changed.modified_count:
        await db.payments.update_one({"_id": payment["_id"]}, {"$set": {
            "status": "PAYMENT_VERIFIED", "utr": utr,
            "transaction_id": gateway_data.get("transaction_id"),
            "sender_name": gateway_data.get("sender_name"),
            "payment_time": gateway_data.get("payment_time"),
            "verified_at": now, "verified_by": "FamGateway"}})
        await _add_status_history(db, oid, order.get("order_status", "CREATED"), "PAYMENT_VERIFIED",
            "famgateway", "FamGateway", "Online payment verified. UTR: " + utr)
        if order.get("customer_id"):
            await db.notifications.insert_one({"user_id": order["customer_id"], "title": "Payment verified",
                "body": "Payment for order " + order["order_number"] + " has been confirmed.",
                "read": False, "created_at": now})
        if order.get("customer_email"):
            email_svc.payment_verified(to_email=order["customer_email"],
                name=order.get("customer_name", ""), order_number=order["order_number"],
                amount=float(order.get("amount", 0)))
        await audit_log("famgateway_payment_verified", "famgateway", "FamGateway", "order", oid, {"utr": utr})

@router.post("/{oid}/payment/create")
async def create_famgateway_payment(oid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        order = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order or order.get("customer_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("payment_status") == "PAYMENT_VERIFIED":
        raise HTTPException(status_code=400, detail="Order already paid")
    amount = float(order.get("amount", 0))
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid order amount")
    now = datetime.now(timezone.utc).isoformat()
    existing = await db.payments.find_one({"order_id": oid, "provider": "famgateway",
        "status": "PAYMENT_PENDING", "expires_at": {"$gt": now}})
    if existing:
        return {"order_id": existing["provider_order_id"], "amount": amount, "payable_amount": existing.get("amount", amount),
            "upi_intent": existing.get("upi_intent"), "checkout_url": existing.get("checkout_url"),
            "qr_url": existing.get("qr_url"), "expires_at": existing.get("expires_at")}
    frontend = os.environ.get("FRONTEND_URL", "https://zeroaxis.in").rstrip("/")
    payload = {"amount": round(amount, 2),
        "customer_name": order.get("customer_name") or user.get("name") or "ZEROAXIS Customer",
        "customer_email": order.get("customer_email") or user.get("email"),
        "redirect_url": frontend + "/dashboard"}
    webhook = os.environ.get("FAMGATEWAY_WEBHOOK_URL", "").strip()
    if webhook:
        payload["webhook_url"] = webhook
    response = await _famgateway_request("POST", "/api/create-order", payload=payload)
    gateway = _gateway_data(response)
    provider_id = str(gateway.get("order_id") or "").strip()
    if not provider_id or not (gateway.get("upi_intent") or gateway.get("checkout_url")):
        raise HTTPException(status_code=502, detail="Payment provider returned incomplete checkout details")
    if gateway.get("amount") is not None and not _amount_matches(gateway.get("amount"), amount):
        raise HTTPException(status_code=502, detail="Payment provider returned a different base amount")
    try:
        payable_amount = round(float(gateway.get("payable_amount", gateway.get("amount", amount))), 2)
    except (TypeError, ValueError):
        raise HTTPException(status_code=502, detail="Payment provider returned an invalid payable amount")
    if payable_amount <= 0:
        raise HTTPException(status_code=502, detail="Payment provider returned an invalid payable amount")
    from datetime import timedelta
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    payment = {"order_id": oid, "customer_id": user["id"], "provider": "famgateway",
        "provider_order_id": provider_id, "method": "UPI", "amount": payable_amount, "order_amount": amount,
        "status": "PAYMENT_PENDING", "upi_intent": gateway.get("upi_intent"),
        "checkout_url": gateway.get("checkout_url"), "qr_url": gateway.get("qr_url"),
        "expires_at": expires_at, "created_at": now}
    await db.payments.insert_one(payment)
    await db.orders.update_one({"_id": order["_id"]}, {"$set": {
        "payment_status": "PAYMENT_PENDING", "order_status": "PAYMENT_PENDING", "updated_at": now}})
    await _add_status_history(db, oid, order.get("order_status", "CREATED"), "PAYMENT_PENDING",
        user["id"], user["email"], "FamGateway checkout created")
    await audit_log("famgateway_checkout_created", user["id"], user["email"], "order", oid,
        {"provider_order_id": provider_id})
    return {"order_id": provider_id, "amount": amount, "payable_amount": payable_amount, "upi_intent": gateway.get("upi_intent"),
        "checkout_url": gateway.get("checkout_url"), "qr_url": gateway.get("qr_url"), "expires_at": expires_at}

@router.get("/{oid}/payment/status")
async def check_famgateway_payment(oid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        order = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order or (user["role"] != "admin" and order.get("customer_id") != user["id"]):
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("payment_status") == "PAYMENT_VERIFIED":
        return {"status": "success", "payment_status": "PAYMENT_VERIFIED"}
    payment = await db.payments.find_one({"order_id": oid, "provider": "famgateway",
        "status": {"$in": ["PAYMENT_PENDING", "PAYMENT_VERIFIED"]}}, sort=[("created_at", -1)])
    if not payment:
        raise HTTPException(status_code=404, detail="No FamGateway checkout found")
    response = await _famgateway_request("GET", "/api/verify-order.php",
        params={"order_id": payment["provider_order_id"]})
    gateway = _gateway_data(response)
    status = str(gateway.get("status") or response.get("status") or "").lower()
    if status == "success" or gateway.get("is_paid") is True:
        if not _amount_matches(gateway.get("payable_amount", gateway.get("amount", payment["amount"])), payment["amount"]):
            raise HTTPException(status_code=409, detail="Verified payment amount mismatch")
        await _mark_famgateway_paid(db, payment, order, gateway)
        return {"status": "success", "payment_status": "PAYMENT_VERIFIED"}
    if status == "expired" or gateway.get("is_expired") is True:
        now = datetime.now(timezone.utc).isoformat()
        await db.payments.update_one({"_id": payment["_id"], "status": "PAYMENT_PENDING"},
            {"$set": {"status": "EXPIRED", "updated_at": now}})
        await db.orders.update_one({"_id": order["_id"], "payment_status": "PAYMENT_PENDING"},
            {"$set": {"payment_status": "UNPAID", "order_status": "CREATED", "updated_at": now}})
        return {"status": "expired", "payment_status": "UNPAID"}
    return {"status": "pending", "payment_status": "PAYMENT_PENDING", "checkout": {
        "order_id": payment.get("provider_order_id"), "amount": payment.get("order_amount", payment.get("amount")), "payable_amount": payment.get("amount"),
        "upi_intent": payment.get("upi_intent"), "checkout_url": payment.get("checkout_url"),
        "qr_url": payment.get("qr_url"), "expires_at": payment.get("expires_at")}}

@router.post("/famgateway/webhook")
async def famgateway_webhook(request: Request):
    api_key = os.environ.get("FAMGATEWAY_API_KEY", "").strip()
    if not api_key:
        raise HTTPException(status_code=503, detail="Payment provider not configured")
    raw = await request.body()
    signature = request.headers.get("x-famgateway-signature", "")
    expected = hmac.new(api_key.encode(), raw, hashlib.sha256).hexdigest()
    if not signature or not hmac.compare_digest(expected, signature.strip()):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        event = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    if event.get("event") != "payment.success" and str(event.get("status", "")).lower() != "success":
        return {"status": "ignored"}
    provider_id = str(event.get("order_id") or "").strip()
    if not provider_id:
        raise HTTPException(status_code=400, detail="Missing provider order ID")
    db = get_db()
    payment = await db.payments.find_one({"provider": "famgateway", "provider_order_id": provider_id})
    if not payment:
        raise HTTPException(status_code=404, detail="Payment session not found")
    order = await db.orders.find_one({"_id": ObjectId(payment["order_id"])})
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if not _amount_matches(event.get("payable_amount", event.get("amount")), payment["amount"]):
        raise HTTPException(status_code=409, detail="Webhook amount mismatch")
    confirmed_response = await _famgateway_request("GET", "/api/verify-order.php",
        params={"order_id": provider_id})
    confirmed = _gateway_data(confirmed_response)
    if str(confirmed.get("status") or confirmed_response.get("status") or "").lower() != "success" and confirmed.get("is_paid") is not True:
        raise HTTPException(status_code=409, detail="Provider has not confirmed this payment")
    if not _amount_matches(confirmed.get("payable_amount", confirmed.get("amount")), payment["amount"]):
        raise HTTPException(status_code=409, detail="Verified payment amount mismatch")
    await _mark_famgateway_paid(db, payment, order, confirmed)
    return {"status": "received"}

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
