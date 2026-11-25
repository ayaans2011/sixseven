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


async def _restore_legacy_payment_order_status(db, order: dict, payment: dict | None = None):
    """Repair old records where PAYMENT_PENDING was incorrectly written to order_status."""
    if not order or order.get("order_status") != "PAYMENT_PENDING":
        return order
    oid = str(order["_id"])
    if payment is None:
        payment = await db.payments.find_one(
            {"order_id": oid, "provider": "famgateway"},
            sort=[("created_at", -1)])
    restored = payment.get("previous_order_status") if payment else None
    allowed = {"ORDER_RECEIVED", "DEVELOPER_ASSIGNED", "WORK_STARTED", "IN_PROGRESS", "READY_FOR_DELIVERY", "COMPLETED"}
    if restored not in allowed:
        after_work = order.get("payment_due_stage") == "AFTER_WORK" or order.get("payment_timing") == "LAST"
        restored = "READY_FOR_DELIVERY" if after_work else (
            "DEVELOPER_ASSIGNED" if order.get("assigned_developer") else "ORDER_RECEIVED")
    now = datetime.now(timezone.utc).isoformat()
    result = await db.orders.update_one(
        {"_id": order["_id"], "order_status": "PAYMENT_PENDING"},
        {"$set": {"order_status": restored, "updated_at": now}})
    if result.modified_count:
        await _add_status_history(db, oid, "PAYMENT_PENDING", restored,
            "system", "ZEROAXIS", "Repaired legacy order/payment status mismatch")
        order["order_status"] = restored
        order["updated_at"] = now
    return order


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
        "discount_amount": o.get("discount_amount", 0), "payable_amount": o.get("payable_amount", o.get("amount", 0)), "coupon_code": o.get("coupon_code"),
        "requirement": o.get("requirement"),
        "notes": o.get("notes"),
        "payment_status": o.get("payment_status", "UNPAID"),
        "order_status": o.get("order_status", "ORDER_RECEIVED"),
        "assigned_developer": o.get("assigned_developer"),
        "payment_timing": o.get("payment_timing"),
        "payment_requested": bool(o.get("payment_requested", False)),
        "payment_due_stage": o.get("payment_due_stage"),
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
        "order_status": "ORDER_RECEIVED",
        "assigned_developer": None,
        "payment_timing": None,
        "payment_requested": False,
        "payment_due_stage": None,
        "created_at": now,
        "updated_at": now,
    }
    res = await db.orders.insert_one(doc)
    doc["_id"] = res.inserted_id
    await _add_status_history(db, str(res.inserted_id), "", "ORDER_RECEIVED", user["id"], user["email"], "Order received; awaiting admin review")
    await notify_user(user["id"], "Order received", f"We received order {number} for {service['name']}. Our team will review it, assign a developer and confirm when payment is due.", now=now)
    admin_msg = f"Order {number} was created by {user.get('name') or user['email']} for {service['name']} (₹{float(service.get('price', 0)):,.0f})."
    await notify_admins("New order received", admin_msg, now=now)
    admins = await db.users.find({"role": "admin", "disabled": {"$ne": True}}, {"email": 1}).to_list(1000)
    for a in admins:
        if a.get("email"): email_svc.admin_event(to_email=a["email"], event_title="New order received", message=admin_msg)
    await audit_log("order_created", user["id"], user["email"], "order", str(res.inserted_id), {"number": number})
    email_svc.order_created(
        to_email=user["email"], name=user.get("name", ""),
        order_number=number, tracking_number=tracking_token, service_name=service["name"], amount=float(service.get("price", 0)),
    )
    return _serialize(doc)


@router.get("/mine")
async def my_orders(user=Depends(get_current_user)):
    db = get_db()
    items = await db.orders.find({"customer_id": user["id"]}).sort("created_at", -1).to_list(500)
    for item in items:
        await _restore_legacy_payment_order_status(db, item)
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
    await _restore_legacy_payment_order_status(db, o)
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
    await _restore_legacy_payment_order_status(db, o)
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
            "provider": p.get("provider"), "proof_file_id": p.get("proof_file_id"),
            "proof_name": p.get("proof_name"), "rejection_reason": p.get("rejection_reason"),
            "submitted_by": p.get("submitted_by"),
            "review_note": p.get("review_note"),
        } for p in payments],
    }



# ZapUPI integration
ZAPUPI_API_BASE = "https://pay.zapupi.com/api"
zapupi_logger = logging.getLogger("zeroaxis.zapupi")


def _zapupi_key():
    key = os.environ.get("ZAPUPI_API_KEY", "").strip()
    if not key:
        raise HTTPException(status_code=503, detail="ZapUPI is not configured")
    return key


def _zapupi_data(response: dict) -> dict:
    if not isinstance(response, dict):
        return {}
    nested = response.get("data")
    return {**response, **nested} if isinstance(nested, dict) else response


async def _zapupi_post(endpoint: str, payload: dict) -> dict:
    try:
        async with httpx.AsyncClient(timeout=25.0, follow_redirects=False) as client:
            response = await client.post(
                ZAPUPI_API_BASE + endpoint,
                json=payload,
                headers={"Accept": "application/json", "Content-Type": "application/json"},
            )
            try:
                result = response.json()
            except ValueError:
                result = {}
            if response.status_code >= 400:
                code = result.get("message") or result.get("error") or "provider_error"
                zapupi_logger.warning("ZapUPI API rejected request: status=%s reason=%s",
                                      response.status_code, str(code)[:120])
                raise HTTPException(status_code=502, detail="ZapUPI could not process the payment request")
            if not isinstance(result, dict):
                raise HTTPException(status_code=502, detail="ZapUPI returned an invalid response")
            return result
    except HTTPException:
        raise
    except httpx.HTTPError:
        zapupi_logger.exception("ZapUPI API request failed")
        raise HTTPException(status_code=502, detail="Could not contact ZapUPI")


def _zapupi_amount_matches(actual, expected) -> bool:
    try:
        return round(float(actual), 2) == round(float(expected), 2)
    except (TypeError, ValueError):
        return False


async def _mark_zapupi_paid(db, payment: dict, order: dict, provider_data: dict):
    if payment.get("provider") != "zapupi" or payment.get("order_id") != str(order["_id"]):
        raise HTTPException(status_code=409, detail="ZapUPI payment session does not match this order")
    if str(provider_data.get("status") or "").strip().lower() != "success":
        raise HTTPException(status_code=409, detail="ZapUPI has not confirmed a successful payment")
    if str(provider_data.get("environment") or "").strip().lower() not in {"cashier", "zappay"}:
        raise HTTPException(status_code=409, detail="ZapUPI test payments cannot be accepted as live payments")
    if str(provider_data.get("order_id") or "").strip() != payment.get("provider_order_id"):
        raise HTTPException(status_code=409, detail="ZapUPI order reference mismatch")
    if not _zapupi_amount_matches(provider_data.get("amount"), payment.get("amount")):
        raise HTTPException(status_code=409, detail="ZapUPI payment amount mismatch")
    txn_id = str(provider_data.get("txn_id") or "").strip()
    if not txn_id or txn_id.upper().startswith("DUMMY"):
        raise HTTPException(status_code=409, detail="ZapUPI transaction ID is missing or belongs to test mode")
    duplicate = await db.payments.find_one({
        "provider": "zapupi", "txn_id": txn_id,
        "order_id": {"$ne": str(order["_id"])}})
    if duplicate:
        raise HTTPException(status_code=409, detail="ZapUPI transaction is already linked to another order")

    now = datetime.now(timezone.utc).isoformat()
    oid = str(order["_id"])
    restored = payment.get("previous_order_status")
    if restored not in {"ORDER_RECEIVED", "DEVELOPER_ASSIGNED", "WORK_STARTED", "IN_PROGRESS", "READY_FOR_DELIVERY", "COMPLETED"}:
        restored = "READY_FOR_DELIVERY" if order.get("payment_due_stage") == "AFTER_WORK" else (
            "DEVELOPER_ASSIGNED" if order.get("assigned_developer") else "ORDER_RECEIVED")
    order_update = {"payment_status": "PAYMENT_VERIFIED", "payment_requested": False, "updated_at": now}
    if order.get("order_status") == "PAYMENT_PENDING":
        order_update["order_status"] = restored
    changed = await db.orders.update_one(
        {"_id": order["_id"], "payment_status": {"$ne": "PAYMENT_VERIFIED"}},
        {"$set": order_update})
    await db.payments.update_one({"_id": payment["_id"]}, {"$set": {
        "status": "PAYMENT_VERIFIED", "txn_id": txn_id,
        "utr": provider_data.get("utr"), "transaction_id": provider_data.get("utr") or txn_id,
        "environment": provider_data.get("environment"),
        "verified_at": now, "verified_by": "ZapUPI", "updated_at": now}})
    if changed.modified_count:
        if order.get("order_status") == "PAYMENT_PENDING":
            await _add_status_history(db, oid, "PAYMENT_PENDING", restored,
                "system", "ZapUPI", "Payment confirmed by ZapUPI order-status API")
        if order.get("coupon_id"):
            redeemed = await db.orders.update_one(
                {"_id": order["_id"], "coupon_redeemed": {"$ne": True}},
                {"$set": {"coupon_redeemed": True}})
            if redeemed.modified_count:
                await db.coupons.update_one({"_id": ObjectId(order["coupon_id"])}, {"$inc": {"used_count": 1}})
        if order.get("customer_id"):
            await db.notifications.insert_one({"user_id": order["customer_id"], "title": "Payment verified",
                "body": "Payment for order " + order["order_number"] + " has been confirmed.",
                "read": False, "created_at": now})
        if order.get("customer_email"):
            email_svc.payment_verified(to_email=order["customer_email"],
                name=order.get("customer_name", ""),
                order_number=order["order_number"],
                amount=float(order.get("payable_amount", order.get("amount", 0))))
        await audit_log("zapupi_payment_verified", "zapupi", "ZapUPI", "order", oid,
            {"txn_id": txn_id})


async def _fetch_zapupi_order_status(provider_order_id: str) -> dict:
    response = await _zapupi_post("/order-status", {
        "zap_key": _zapupi_key(),
        "order_id": provider_order_id,
    })
    data = _zapupi_data(response)
    # The API's outer response may use status=success while data.status is the
    # actual payment state. Require the order details, not merely outer success.
    if not data.get("order_id") or not data.get("status"):
        raise HTTPException(status_code=502, detail="ZapUPI returned incomplete order-status details")
    return data


@router.post("/{oid}/payment/create")
async def create_zapupi_payment(oid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        order = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order or order.get("customer_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Order not found")
    await _restore_legacy_payment_order_status(db, order)
    if order.get("payment_status") == "PAYMENT_VERIFIED":
        raise HTTPException(status_code=400, detail="Order already paid")
    if order.get("payment_status") == "PENDING_VERIFICATION":
        raise HTTPException(status_code=409, detail="An offline payment proof is awaiting administrator review")
    if order.get("payment_status") not in {"UNPAID", "PAYMENT_REJECTED", "PAYMENT_PENDING"}:
        raise HTTPException(status_code=409, detail="Order is not in a payable state")
    if not order.get("payment_requested"):
        raise HTTPException(status_code=403, detail="Payment has not been requested by the administrator yet")
    amount = round(float(order.get("payable_amount", order.get("amount", 0))), 2)
    if amount < 1 or amount > 500000:
        raise HTTPException(status_code=400, detail="Payment amount must be between ₹1 and ₹5,00,000")
    _zapupi_key()
    existing = await db.payments.find_one({"order_id": oid, "provider": "zapupi",
        "status": "PAYMENT_PENDING", "payment_url": {"$exists": True, "$ne": ""}},
        sort=[("created_at", -1)])
    if existing:
        return {"order_id": existing["provider_order_id"], "amount": amount,
                "payment_url": existing["payment_url"]}

    provider_order_id = "ZX" + secrets.token_hex(12).upper()
    payload = {
        "zap_key": _zapupi_key(),
        "order_id": provider_order_id,
        "amount": f"{amount:.2f}",
        "remark": (str(order.get("order_number") or oid) + " | " +
                   str(order.get("service_name") or "ZEROAXIS order"))[:180],
        "webhook_url": os.environ.get(
            "ZAPUPI_WEBHOOK_URL",
            "https://sixseven-backend-maft.onrender.com/api/orders/zapupi/webhook",
        ).strip(),
    }
    mobile = str(order.get("customer_mobile") or user.get("phone") or "").strip()
    if mobile:
        payload["customer_mobile"] = mobile
    response = await _zapupi_post("/create-order", payload)
    provider = _zapupi_data(response)
    outer_status = str(response.get("status") or "").strip().lower()
    if outer_status not in {"success", "ok"} and not provider.get("payment_url"):
        raise HTTPException(status_code=502, detail="ZapUPI did not create the payment order")
    payment_url = str(provider.get("payment_url") or "").strip()
    returned_order_id = str(provider.get("order_id") or provider_order_id).strip()
    if not payment_url or returned_order_id != provider_order_id:
        raise HTTPException(status_code=502, detail="ZapUPI returned incomplete or mismatched checkout details")
    if not payment_url.startswith("https://"):
        raise HTTPException(status_code=502, detail="ZapUPI returned an insecure payment URL")

    now = datetime.now(timezone.utc).isoformat()
    payment = {
        "order_id": oid, "customer_id": user["id"], "provider": "zapupi",
        "provider_order_id": provider_order_id, "method": "UPI",
        "amount": amount, "order_amount": amount, "previous_order_status": order.get("order_status", "ORDER_RECEIVED"),
        "status": "PAYMENT_PENDING", "payment_url": payment_url, "created_at": now,
    }
    await db.payments.insert_one(payment)
    await db.orders.update_one({"_id": order["_id"], "payment_status": {"$ne": "PAYMENT_VERIFIED"}},
        {"$set": {"payment_status": "PAYMENT_PENDING", "updated_at": now}})
    await audit_log("zapupi_checkout_created", user["id"], user["email"], "order", oid,
        {"provider_order_id": provider_order_id})
    return {"order_id": provider_order_id, "amount": amount, "payment_url": payment_url}


@router.get("/{oid}/payment/status")
async def check_zapupi_payment(oid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        order = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Order not found")
    if not order or (user["role"] != "admin" and order.get("customer_id") != user["id"]):
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("payment_status") == "PAYMENT_VERIFIED":
        return {"status": "success", "payment_status": "PAYMENT_VERIFIED"}
    payment = await db.payments.find_one({"order_id": oid, "provider": "zapupi",
        "status": {"$in": ["PAYMENT_PENDING", "PAYMENT_VERIFIED"]}},
        sort=[("created_at", -1)])
    if not payment:
        raise HTTPException(status_code=404, detail="No ZapUPI checkout found")
    provider = await _fetch_zapupi_order_status(payment["provider_order_id"])
    state = str(provider.get("status") or "").strip().lower()
    if state == "success":
        await _mark_zapupi_paid(db, payment, order, provider)
        return {"status": "success", "payment_status": "PAYMENT_VERIFIED"}
    if state == "failed":
        now = datetime.now(timezone.utc).isoformat()
        await db.payments.update_one({"_id": payment["_id"], "status": "PAYMENT_PENDING"},
            {"$set": {"status": "PAYMENT_REJECTED", "updated_at": now}})
        await db.orders.update_one({"_id": order["_id"], "payment_status": "PAYMENT_PENDING"},
            {"$set": {"payment_status": "UNPAID", "updated_at": now}})
        return {"status": "failed", "payment_status": "UNPAID"}
    return {"status": "pending", "payment_status": "PAYMENT_PENDING",
        "checkout": {"order_id": payment.get("provider_order_id"),
                     "payment_url": payment.get("payment_url")}}


@router.post("/zapupi/webhook")
async def zapupi_webhook(request: Request):
    # ZapUPI's supplied guide does not document webhook signatures. Therefore
    # never trust this POST's status/amount alone: verify against its status API.
    try:
        event = await request.json()
        if not isinstance(event, dict):
            return {"status": "ok"}
        provider_order_id = str(event.get("order_id") or "").strip()
        if not provider_order_id:
            return {"status": "ok"}
        db = get_db()
        payment = await db.payments.find_one({
            "provider": "zapupi", "provider_order_id": provider_order_id})
        if not payment:
            zapupi_logger.warning("Ignoring webhook for unknown ZapUPI order")
            return {"status": "ok"}
        order = await db.orders.find_one({"_id": ObjectId(payment["order_id"])})
        if not order:
            return {"status": "ok"}
        provider = await _fetch_zapupi_order_status(provider_order_id)
        state = str(provider.get("status") or "").strip().lower()
        if state == "success":
            await _mark_zapupi_paid(db, payment, order, provider)
        elif state == "failed":
            now = datetime.now(timezone.utc).isoformat()
            await db.payments.update_one({"_id": payment["_id"], "status": "PAYMENT_PENDING"},
                {"$set": {"status": "PAYMENT_REJECTED", "updated_at": now}})
            await db.orders.update_one({"_id": order["_id"], "payment_status": "PAYMENT_PENDING"},
                {"$set": {"payment_status": "UNPAID", "updated_at": now}})
    except Exception:
        zapupi_logger.exception("ZapUPI webhook could not be processed; payment remains unverified")
    return {"status": "ok"}


@router.post("/{oid}/payment/manual-submit")
async def submit_manual_payment(oid: str, data: dict, user=Depends(get_current_user)):
    if user.get("role") != "customer":
        raise HTTPException(status_code=403, detail="Customer account required")
    method = str(data.get("method") or "").upper().strip()
    if method not in {"CHEQUE", "CASH", "BANK_TRANSFER"}:
        raise HTTPException(status_code=400, detail="Choose cheque, cash or bank transfer")
    reference = str(data.get("reference") or "").strip()[:120]
    proof_id = str(data.get("proof_file_id") or "").strip()
    if not proof_id:
        raise HTTPException(status_code=400, detail="Upload payment proof")
    db = get_db()
    try:
        order = await db.orders.find_one({"_id": ObjectId(oid), "customer_id": user["id"]})
        proof = await db.files.find_one({"_id": ObjectId(proof_id), "parent_type": "order",
            "parent_id": oid, "owner_id": user["id"], "is_deleted": {"$ne": True}})
    except Exception:
        raise HTTPException(status_code=404, detail="Order or proof not found")
    if not order or not proof:
        raise HTTPException(status_code=404, detail="Order or proof not found")
    if proof.get("mime") not in {"application/pdf", "image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=400, detail="Proof must be a PDF or image")
    if not order.get("payment_requested"):
        raise HTTPException(status_code=403, detail="Payment has not been requested by the administrator yet")
    if order.get("payment_status") not in {"UNPAID", "PAYMENT_REJECTED"}:
        raise HTTPException(status_code=409, detail="This order already has a payment in progress or is paid")
    pending = await db.payments.find_one({"order_id": oid, "provider": "manual", "status": "PENDING_VERIFICATION"})
    if pending:
        raise HTTPException(status_code=409, detail="A payment submission is already awaiting review")
    if reference and await db.payments.find_one({"provider": "manual", "reference": reference,
            "status": {"$in": ["PENDING_VERIFICATION", "PAYMENT_VERIFIED"]}}):
        raise HTTPException(status_code=409, detail="This payment reference has already been submitted")
    now = datetime.now(timezone.utc).isoformat()
    claim = await db.orders.update_one({"_id": order["_id"], "payment_status": {"$in": ["UNPAID", "PAYMENT_REJECTED"]}},
        {"$set": {"payment_status": "PENDING_VERIFICATION", "updated_at": now}})
    if not claim.modified_count:
        raise HTTPException(status_code=409, detail="Order payment status changed. Refresh and try again.")
    try:
        await db.payments.insert_one({"order_id": oid, "customer_id": user["id"], "provider": "manual",
            "method": method, "reference": reference, "amount": float(order.get("payable_amount", order.get("amount", 0))),
            "status": "PENDING_VERIFICATION", "proof_file_id": proof_id,
            "proof_name": proof.get("original_name"), "submitted_by": user["email"], "created_at": now})
    except Exception:
        await db.orders.update_one({"_id": order["_id"], "payment_status": "PENDING_VERIFICATION"},
            {"$set": {"payment_status": order.get("payment_status", "UNPAID"), "updated_at": now}})
        raise
    admins = await db.users.find({"role": "admin", "disabled": {"$ne": True}}, {"_id": 1}).to_list(1000)
    for admin_user in admins:
        await db.notifications.insert_one({"user_id": str(admin_user["_id"]), "title": "Payment proof submitted",
            "body": order.get("order_number", "") + " · " + method.replace("_", " ").title() + " payment requires review.",
            "read": False, "created_at": now})
    if order.get("customer_email"):
        email_svc.payment_submitted(to_email=order["customer_email"], name=order.get("customer_name", ""),
            order_number=order.get("order_number", ""), amount=float(order.get("payable_amount", order.get("amount", 0))), reference=reference)
    await audit_log("manual_payment_submitted", user["id"], user["email"], "order", oid,
        {"method": method, "amount": float(order.get("payable_amount", order.get("amount", 0))), "payment_reference": reference})
    return {"success": True, "payment_status": "PENDING_VERIFICATION"}


@router.post("/{oid}/payment/manual-review")
async def review_manual_payment(oid: str, data: dict, admin=Depends(require_admin)):
    payment_id = str(data.get("payment_id") or "").strip()
    decision = str(data.get("decision") or "").upper().strip()
    note = str(data.get("note") or "").strip()[:500]
    if decision not in {"APPROVE", "REJECT"}:
        raise HTTPException(status_code=400, detail="Invalid review decision")
    if decision == "REJECT" and not note:
        raise HTTPException(status_code=400, detail="A rejection reason is required")
    db = get_db()
    try:
        order = await db.orders.find_one({"_id": ObjectId(oid)})
        payment = await db.payments.find_one({"_id": ObjectId(payment_id), "order_id": oid,
            "provider": "manual", "status": "PENDING_VERIFICATION"})
    except Exception:
        raise HTTPException(status_code=404, detail="Order or payment not found")
    if not order or not payment:
        raise HTTPException(status_code=404, detail="Pending manual payment not found")
    if order.get("payment_status") != "PENDING_VERIFICATION":
        raise HTTPException(status_code=409, detail="Order is no longer awaiting offline payment review")
    expected_amount = order.get("payable_amount", order.get("amount", 0))
    if not _amount_matches(payment.get("amount"), expected_amount):
        raise HTTPException(status_code=409, detail="Submitted payment amount does not match the order")
    now = datetime.now(timezone.utc).isoformat()
    if decision == "APPROVE":
        if order.get("payment_status") == "PAYMENT_VERIFIED":
            raise HTTPException(status_code=409, detail="Order is already paid")
        update = {"status": "PAYMENT_VERIFIED", "verified_by": admin["email"], "verified_at": now, "review_note": note}
    else:
        update = {"status": "PAYMENT_REJECTED", "verified_by": admin["email"], "verified_at": now, "rejection_reason": note}
    result = await db.payments.update_one({"_id": payment["_id"], "status": "PENDING_VERIFICATION"}, {"$set": update})
    if not result.modified_count:
        raise HTTPException(status_code=409, detail="Payment was already reviewed")
    new_status = "PAYMENT_VERIFIED" if decision == "APPROVE" else "PAYMENT_REJECTED"
    await db.orders.update_one({"_id": order["_id"], "payment_status": {"$ne": "PAYMENT_VERIFIED"}},
        {"$set": {"payment_status": new_status, "payment_requested": False, "updated_at": now}})
    if decision == "APPROVE" and order.get("coupon_id"):
        redeemed = await db.orders.update_one({"_id": order["_id"], "coupon_redeemed": {"$ne": True}}, {"$set": {"coupon_redeemed": True}})
        if redeemed.modified_count:
            await db.coupons.update_one({"_id": ObjectId(order["coupon_id"])}, {"$inc": {"used_count": 1}})
    title = "Payment verified" if decision == "APPROVE" else "Payment proof rejected"
    body = "Payment for order " + order.get("order_number", "") + (" has been verified." if decision == "APPROVE" else " was rejected. Reason: " + note)
    if order.get("customer_id"):
        await db.notifications.insert_one({"user_id": order["customer_id"], "title": title, "body": body,
            "read": False, "created_at": now})
    if order.get("customer_email"):
        if decision == "APPROVE":
            email_svc.payment_verified(to_email=order["customer_email"], name=order.get("customer_name", ""),
                order_number=order.get("order_number", ""), amount=float(order.get("amount", 0)))
        else:
            email_svc.payment_rejected(to_email=order["customer_email"], name=order.get("customer_name", ""),
                order_number=order.get("order_number", ""), note=note)
    await audit_log("manual_payment_" + ("verified" if decision == "APPROVE" else "rejected"),
        admin["id"], admin["email"], "order", oid, {"payment_id": payment_id, "method": payment.get("method"), "note": note})
    return {"success": True, "payment_status": new_status}


@router.post("/{oid}/workflow")
async def update_order_workflow(oid: str, data: dict, admin=Depends(require_admin)):
    db = get_db()
    try:
        order = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        order = None
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    developer = str(data.get("assigned_developer") or "").strip()[:120]
    timing = str(data.get("payment_timing") or "").upper().strip()
    if timing not in {"FIRST", "LAST"}:
        raise HTTPException(status_code=400, detail="Choose payment before work or after work")
    if order.get("payment_status") == "PAYMENT_VERIFIED" and timing != order.get("payment_timing"):
        raise HTTPException(status_code=409, detail="Payment timing cannot be changed after payment is verified")
    now = datetime.now(timezone.utc).isoformat()
    previous_developer = order.get("assigned_developer")
    next_status = order.get("order_status", "ORDER_RECEIVED")
    if developer and next_status == "ORDER_RECEIVED":
        next_status = "DEVELOPER_ASSIGNED"
    elif not developer and next_status == "DEVELOPER_ASSIGNED":
        next_status = "ORDER_RECEIVED"
    await db.orders.update_one({"_id": order["_id"]}, {"$set": {
        "assigned_developer": developer or None, "payment_timing": timing,
        "order_status": next_status, "updated_at": now,
    }})
    if next_status != order.get("order_status"):
        status_note = "Developer assigned" if developer else "Developer assignment cleared"
        await _add_status_history(db, oid, order.get("order_status", "ORDER_RECEIVED"), next_status,
            admin["id"], admin["email"], status_note)
        if order.get("customer_email"):
            email_svc.status_changed(to_email=order["customer_email"], name=order.get("customer_name", ""),
                order_number=order.get("order_number", ""), new_status=next_status, note=status_note)
    await audit_log("order_workflow_updated", admin["id"], admin["email"], "order", oid,
        {"assigned_developer": developer or None, "payment_timing": timing, "previous_developer": previous_developer})
    if order.get("customer_id"):
        await db.notifications.insert_one({"user_id": order["customer_id"], "title": "Order plan updated",
            "body": "Your order " + order.get("order_number", "") + " has been assigned to " +
                (developer if developer else "our team") + ". Payment is scheduled " +
                ("before work starts." if timing == "FIRST" else "after the work is completed."),
            "read": False, "created_at": now})
    return {"success": True, "assigned_developer": developer or None, "payment_timing": timing, "order_status": next_status}


@router.post("/{oid}/payment/request")
async def request_order_payment(oid: str, admin=Depends(require_admin)):
    db = get_db()
    try:
        order = await db.orders.find_one({"_id": ObjectId(oid)})
    except Exception:
        order = None
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if order.get("payment_status") == "PAYMENT_VERIFIED":
        raise HTTPException(status_code=409, detail="Order is already paid")
    if not order.get("payment_timing"):
        raise HTTPException(status_code=409, detail="Set the payment timing in the order workflow first")
    if order.get("payment_timing") == "FIRST":
        if not order.get("assigned_developer"):
            raise HTTPException(status_code=409, detail="Assign a developer before requesting the advance payment")
        if order.get("order_status") not in {"ORDER_RECEIVED", "DEVELOPER_ASSIGNED"}:
            raise HTTPException(status_code=409, detail="Advance payment can only be requested before work starts")
        stage = "BEFORE_WORK"
    else:
        if order.get("order_status") not in {"READY_FOR_DELIVERY", "COMPLETED"}:
            raise HTTPException(status_code=409, detail="Final payment can be requested when the work is ready for delivery")
        stage = "AFTER_WORK"
    if order.get("payment_status") in {"PENDING_VERIFICATION", "PAYMENT_PENDING"}:
        raise HTTPException(status_code=409, detail="A payment is already awaiting confirmation or review")
    now = datetime.now(timezone.utc).isoformat()
    await db.orders.update_one({"_id": order["_id"]}, {"$set": {
        "payment_requested": True, "payment_due_stage": stage, "updated_at": now,
    }})
    if order.get("customer_id"):
        await db.notifications.insert_one({"user_id": order["customer_id"], "title": "Payment requested",
            "body": "ZEROAXIS has requested " + ("advance" if stage == "BEFORE_WORK" else "final") +
                " payment for order " + order.get("order_number", "") + ". You can now open the order and submit payment.",
            "read": False, "created_at": now})
    if order.get("customer_email"):
        email_svc.payment_requested(to_email=order["customer_email"], name=order.get("customer_name", ""),
            order_number=order.get("order_number", ""), amount=float(order.get("payable_amount", order.get("amount", 0))), stage=stage)
    await audit_log("order_payment_requested", admin["id"], admin["email"], "order", oid, {"stage": stage})
    return {"success": True, "payment_due_stage": stage, "payment_requested": True}


# Admin: update order status
@router.post("/{oid}/status")
async def update_status(oid: str, data: OrderStatusUpdate, admin=Depends(require_admin)):
    if data.order_status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    if data.order_status in {"PAYMENT_PENDING", "PAYMENT_SUBMITTED", "PENDING_VERIFICATION", "PAYMENT_VERIFIED"}:
        raise HTTPException(status_code=400, detail="Payment states are managed only by verified payment-provider events.")
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
    for item in items:
        await _restore_legacy_payment_order_status(db, item)
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
