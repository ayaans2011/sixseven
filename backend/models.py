from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime


# ---------- Auth ----------
class RegisterIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: EmailStr
    password: str = Field(min_length=6, max_length=128)
    phone: Optional[str] = None


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class ForgotPasswordIn(BaseModel):
    email: EmailStr


class ResetPasswordIn(BaseModel):
    token: str
    new_password: str = Field(min_length=6, max_length=128)


class ProfileUpdateIn(BaseModel):
    name: Optional[str] = Field(default=None, min_length=2, max_length=80)
    phone: Optional[str] = None
    address: Optional[str] = None
    company: Optional[str] = None


# ---------- Services ----------
class ServiceIn(BaseModel):
    name: str
    slug: str
    description: str
    price: float
    category: Optional[str] = "General"
    active: bool = True


class ServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    active: Optional[bool] = None


# ---------- Enquiries ----------
class EnquiryIn(BaseModel):
    service_id: Optional[str] = None
    service_name: Optional[str] = None
    name: str
    email: EmailStr
    phone: Optional[str] = None
    requirement: str
    message: Optional[str] = ""


class EnquiryResponse(BaseModel):
    response: str
    status: Optional[str] = "responded"  # responded | closed | converted


# ---------- Orders ----------
class OrderIn(BaseModel):
    service_id: str
    requirement: str
    notes: Optional[str] = ""


class OrderStatusUpdate(BaseModel):
    order_status: str
    note: Optional[str] = ""


class PaymentSubmitIn(BaseModel):
    method: str  # UPI / Bank Transfer / Cash / Other
    reference: str
    amount: float
    note: Optional[str] = ""


class PaymentVerifyIn(BaseModel):
    action: str  # verify | reject
    note: Optional[str] = ""


# ---------- Notifications ----------
class NotificationIn(BaseModel):
    user_id: Optional[str] = None  # None means broadcast
    title: str
    body: str


# ---------- Content ----------
class ContentIn(BaseModel):
    key: str
    value: dict


# ---------- Messages ----------
class MessageIn(BaseModel):
    to_user_id: Optional[str] = None  # customer -> admin if None
    body: str


ORDER_STATUSES = [
    "CREATED",
    "PAYMENT_SUBMITTED",
    "PENDING_VERIFICATION",
    "PAYMENT_VERIFIED",
    "WORK_STARTED",
    "IN_PROGRESS",
    "READY_FOR_DELIVERY",
    "COMPLETED",
    "CANCELLED",
]

PAYMENT_STATUSES = [
    "UNPAID",
    "PAYMENT_SUBMITTED",
    "PENDING_VERIFICATION",
    "PAYMENT_VERIFIED",
    "PAYMENT_REJECTED",
    "REFUNDED",
]
