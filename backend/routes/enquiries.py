from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId
import hashlib
import secrets as _secrets

from database import get_db
from security import get_current_user, require_admin, hash_password, audit_log
from models import EnquiryIn, EnquiryResponse
from counters import generate_enquiry_number, generate_order_number
from services import email as email_svc
from services.notifications import notify_user, notify_admins

router = APIRouter(prefix="/api/enquiries", tags=["enquiries"])


def _serialize(e: dict) -> dict:
    return {
        "id": str(e["_id"]),
        "enquiry_number": e.get("enquiry_number"),
        "customer_id": e.get("customer_id"),
        "service_id": e.get("service_id"),
        "service_name": e.get("service_name"),
        "name": e.get("name"),
        "email": e.get("email"),
        "phone": e.get("phone"),
        "requirement": e.get("requirement"),
        "message": e.get("message"),
        "status": e.get("status", "new"),
        "admin_response": e.get("admin_response"),
        "converted_order_id": e.get("converted_order_id"),
        "created_at": e.get("created_at"),
        "updated_at": e.get("updated_at"),
    }


@router.post("/public")
async def create_enquiry_public(data: EnquiryIn):
    """Public enquiry: create/link a customer account and send a secure activation link."""
    db = get_db()
    email = data.email.lower().strip()
    number = await generate_enquiry_number()
    now = datetime.now(timezone.utc)
    customer_id = None
    new_customer = False

    # Link to an existing account when the email is already registered.
    existing = await db.users.find_one({"email": email})
    if existing:
        customer_id = str(existing["_id"])
    else:
        # Create an account with a random unusable-by-email password. The customer
        # chooses the real password through a one-time activation link.
        random_password = _secrets.token_urlsafe(32)
        user_doc = {
            "email": email,
            "name": data.name.strip(),
            "phone": data.phone,
            "password_hash": hash_password(random_password),
            "role": "customer",
            "account_status": "pending_activation",
            "created_at": now.isoformat(),
            "created_via": "public_enquiry",
        }
        res_user = await db.users.insert_one(user_doc)
        customer_id = str(res_user.inserted_id)
        new_customer = True

        token = _secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        await db.account_activation_tokens.insert_one({
            "user_id": customer_id,
            "token_hash": token_hash,
            "used": False,
            "expires_at": now + timedelta(minutes=30),
            "created_at": now,
        })
        email_svc.enquiry_account_activation(
            to_email=email,
            name=data.name.strip(),
            enquiry_number=number,
            activation_token=token,
        )

    doc = data.model_dump()
    doc.update({
        "email": email,
        "enquiry_number": number,
        "customer_id": customer_id,
        "status": "new",
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    })
    res = await db.enquiries.insert_one(doc)
    doc["_id"] = res.inserted_id

    await notify_user(customer_id, "Enquiry received", f"Your enquiry {number} has been received. Our team will review it and respond.", now=now.isoformat())
    await notify_admins("New enquiry received", f"Enquiry {number} from {data.name.strip()} ({email})" + (f" about {doc.get('service_name')}." if doc.get("service_name") else "."))
    email_svc.enquiry_received(
        to_email=email, name=data.name.strip(),
        enquiry_number=number, service_name=doc.get("service_name"),
    )
    await audit_log(
        "public_enquiry_received",
        customer_id,
        email,
        "enquiry",
        str(res.inserted_id),
        {"new_customer": new_customer},
    )
    return _serialize(doc)


@router.post("")
async def create_enquiry(data: EnquiryIn, user=Depends(get_current_user)):
    db = get_db()
    number = await generate_enquiry_number()
    doc = data.model_dump()
    doc.update({
        "enquiry_number": number,
        "customer_id": user["id"],
        "status": "new",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    res = await db.enquiries.insert_one(doc)
    await notify_user(user["id"], "Enquiry received", f"Your enquiry {number} has been received. Our team will review it and respond.", now=doc["created_at"])
    await notify_admins("New enquiry received", f"Enquiry {number} from {user.get('name') or user['email']}" + (f" about {doc.get('service_name')}." if doc.get("service_name") else "."))
    doc["_id"] = res.inserted_id
    email_svc.enquiry_received(
        to_email=user["email"], name=user.get("name", ""),
        enquiry_number=number, service_name=doc.get("service_name"),
    )
    return _serialize(doc)


@router.get("/mine")
async def my_enquiries(user=Depends(get_current_user)):
    db = get_db()
    items = await db.enquiries.find({"customer_id": user["id"]}).sort("created_at", -1).to_list(500)
    return [_serialize(e) for e in items]


@router.get("/{eid}")
async def get_enquiry(eid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        e = await db.enquiries.find_one({"_id": ObjectId(eid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] != "admin" and e.get("customer_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    return _serialize(e)


@router.get("/admin/all")
async def admin_list(admin=Depends(require_admin)):
    db = get_db()
    items = await db.enquiries.find({}).sort("created_at", -1).to_list(1000)
    return [_serialize(e) for e in items]


@router.post("/{eid}/respond")
async def respond(eid: str, data: EnquiryResponse, admin=Depends(require_admin)):
    db = get_db()
    try:
        oid = ObjectId(eid)
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    e = await db.enquiries.find_one({"_id": oid})
    if not e:
        raise HTTPException(status_code=404, detail="Not found")
    await db.enquiries.update_one({"_id": oid}, {"$set": {
        "admin_response": data.response,
        "status": data.status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }})
    if e.get("customer_id"):
        await notify_user(e["customer_id"], "Enquiry response", f"ZEROAXIS Support responded to your enquiry {e.get('enquiry_number')}: {data.response}")
    await audit_log("enquiry_responded", admin["id"], admin["email"], "enquiry", eid)
    if e.get("email"):
        email_svc.enquiry_response(
            to_email=e["email"], name=e.get("name", ""),
            enquiry_number=e.get("enquiry_number", ""), response_text=data.response,
        )
    e2 = await db.enquiries.find_one({"_id": oid})
    return _serialize(e2)


@router.post("/{eid}/convert")
async def convert_to_order(eid: str, admin=Depends(require_admin), service_id: str | None = None):
    """Admin: convert an enquiry into an order for the same customer."""
    db = get_db()
    try:
        oid = ObjectId(eid)
    except Exception:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    e = await db.enquiries.find_one({"_id": oid})
    if not e:
        raise HTTPException(status_code=404, detail="Enquiry not found")
    if e.get("converted_order_id"):
        raise HTTPException(status_code=400, detail="Already converted to an order")

    sid = service_id or e.get("service_id")
    if not sid:
        raise HTTPException(status_code=400, detail="Service is required. Pass service_id.")
    try:
        service = await db.services.find_one({"_id": ObjectId(sid), "active": True})
    except Exception:
        raise HTTPException(status_code=404, detail="Service not found")
    if not service:
        raise HTTPException(status_code=404, detail="Service not found")

    customer_id = e.get("customer_id")
    customer_email = (e.get("email") or "").lower().strip()
    customer_name = e.get("name") or ""
    if not customer_id:
        cust = await db.users.find_one({"email": customer_email}) if customer_email else None
        if not cust:
            random_password = _secrets.token_urlsafe(32)
            new_doc = {
                "email": customer_email,
                "name": customer_name or "Customer",
                "phone": e.get("phone"),
                "password_hash": hash_password(random_password),
                "role": "customer",
                "account_status": "pending_activation",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_via": "enquiry_conversion",
            }
            res_u = await db.users.insert_one(new_doc)
            customer_id = str(res_u.inserted_id)
            token = _secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            await db.account_activation_tokens.insert_one({
                "user_id": customer_id,
                "token_hash": token_hash,
                "used": False,
                "expires_at": datetime.now(timezone.utc) + timedelta(minutes=30),
                "created_at": datetime.now(timezone.utc),
            })
            email_svc.enquiry_account_activation(
                to_email=customer_email,
                name=customer_name or "Customer",
                enquiry_number=e.get("enquiry_number", ""),
                activation_token=token,
            )
        else:
            customer_id = str(cust["_id"])
            customer_name = cust.get("name") or customer_name
    else:
        cu = await db.users.find_one({"_id": ObjectId(customer_id)})
        if cu:
            customer_email = cu.get("email") or customer_email
            customer_name = cu.get("name") or customer_name

    order_number = await generate_order_number()
    now = datetime.now(timezone.utc).isoformat()
    order_doc = {
        "order_number": order_number,
        "tracking_number": order_number,
        "customer_id": customer_id,
        "customer_name": customer_name,
        "customer_email": customer_email,
        "service_id": sid,
        "service_name": service["name"],
        "amount": float(service.get("price", 0)),
        "requirement": e.get("requirement", ""),
        "notes": f"Converted from enquiry {e.get('enquiry_number','')}",
        "payment_status": "UNPAID",
        "order_status": "CREATED",
        "converted_from_enquiry_id": eid,
        "created_at": now,
        "updated_at": now,
    }
    res_o = await db.orders.insert_one(order_doc)
    order_id = str(res_o.inserted_id)

    await db.order_status_history.insert_one({
        "order_id": order_id,
        "from_status": "",
        "to_status": "CREATED",
        "actor_id": admin["id"],
        "actor_email": admin["email"],
        "note": f"Converted from enquiry {e.get('enquiry_number','')}",
        "timestamp": now,
    })

    await db.enquiries.update_one({"_id": oid}, {"$set": {
        "status": "converted",
        "converted_order_id": order_id,
        "updated_at": now,
    }})

    await db.notifications.insert_one({
        "user_id": customer_id,
        "title": "Order created from your enquiry",
        "body": f"We've turned your enquiry {e.get('enquiry_number','')} into order {order_number}. Please complete payment to proceed.",
        "read": False,
        "created_at": now,
    })
    await audit_log("enquiry_converted", admin["id"], admin["email"], "enquiry", eid,
                    {"order_id": order_id, "order_number": order_number})

    if customer_email:
        email_svc.order_created(
            to_email=customer_email, name=customer_name,
            order_number=order_number, service_name=service["name"],
            amount=float(service.get("price", 0)),
        )
    return {
        "success": True,
        "order_id": order_id,
        "order_number": order_number,
        "new_customer_created": bool(customer_id and not e.get("customer_id")),
    }
