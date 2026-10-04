"""ZEROAXIS transactional email service (Emergent-managed Resend proxy).

All templates live server-side. Callers pass IDs and pre-validated data only —
never HTML from the client (G4). The guardrail gate (_assert_safe_email) runs on
every send. On failure, we log and swallow so business flows never break.
"""
import os
import re
import ipaddress
import logging
import asyncio
import httpx
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

EMAIL_BASE_URL = "https://integrations.emergentagent.com"


def _cfg(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


# ---------- Guardrail gate ----------
_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = (
    "reply with your password", "reply with the code", "send your password", "cvv",
    "send us your password", "enter your password below", "confirm your card number",
    "your full card number", "seed phrase", "recovery phrase", "verify your card",
    "social security number", "confirm your bank details",
)
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []

    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan(); scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} != real link host {real!r} (G3)")


# ---------- Core send ----------
async def _send_email(*, to: str, subject: str, html: str) -> str | None:
    """Low-level send. Returns email id or None on failure. Never raises."""
    key = _cfg("EMERGENT_EMAIL_KEY")
    from_name = _cfg("EMAIL_FROM_NAME", "ZEROAXIS")
    reply_to = _cfg("EMAIL_REPLY_TO")
    if not key:
        logger.warning("EMERGENT_EMAIL_KEY missing — skipping email send")
        return None
    if not to or "@" not in to:
        logger.warning(f"Bad recipient — skipping: {to!r}")
        return None
    try:
        _assert_safe_email(subject, html)
    except ValueError as e:
        logger.error(f"Email guardrail rejected send: {e}")
        return None
    payload = {"to": [to], "subject": subject, "html": html, "from_name": from_name}
    if reply_to:
        payload["contact_email"] = reply_to
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": key},
                json=payload,
            )
        resp.raise_for_status()
        return resp.json().get("id")
    except httpx.HTTPStatusError as e:
        logger.error(f"Email HTTP error {e.response.status_code}: {e.response.text[:300]}")
    except Exception as e:
        logger.error(f"Email send error: {e}")
    return None


def _bg_send(**kwargs):
    """Fire-and-forget send. Never blocks the caller, never raises."""
    try:
        asyncio.create_task(_send_email(**kwargs))
    except RuntimeError:
        # No running loop (e.g. shutdown). Best-effort skip.
        pass


# ---------- Templates ----------
_BRAND = "ZEROAXIS"


def _wrap(inner_html: str, footer_note: str = "") -> str:
    footer_note = footer_note or "We never ask for your password, OTP, or card details by email."
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="background:#f5f6f8;padding:24px 0"><tr><td align="center">'
        f'<table role="presentation" width="600" cellpadding="0" cellspacing="0" '
        f'style="max-width:600px;background:#ffffff;border:1px solid #e5e7eb;'
        f'font-family:Arial,Helvetica,sans-serif;color:#0A1128">'
        f'<tr><td style="padding:20px 28px;border-bottom:1px solid #e5e7eb;background:#0A1128">'
        f'<div style="color:#ffffff;font-size:18px;font-weight:700;letter-spacing:1px">'
        f'{escape(_BRAND)}</div>'
        f'<div style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:2px">'
        f'Technology &amp; Digital Services</div></td></tr>'
        f'<tr><td style="padding:24px 28px;font-size:14px;line-height:1.55">'
        f'{inner_html}</td></tr>'
        f'<tr><td style="padding:14px 28px;border-top:1px solid #e5e7eb;'
        f'font-size:11px;color:#6b7280">Sent by {escape(_BRAND)}. '
        f'{escape(footer_note)}</td></tr></table></td></tr></table>'
    )


def _app_url(path: str = "") -> str:
    base = _cfg("PUBLIC_APP_URL", "").rstrip("/")
    if not base:
        return ""
    p = path if path.startswith("/") else f"/{path}"
    return f"{base}{p}"


def _button(href: str, label: str) -> str:
    if not href or not href.startswith("https://"):
        return ""
    return (
        f'<a href="{escape(href)}" style="display:inline-block;background:#00509E;'
        f'color:#ffffff;text-decoration:none;padding:10px 18px;font-weight:600;'
        f'font-size:13px;border-radius:2px">{escape(label)}</a>'
    )


# ---------- Public template helpers ----------
def enquiry_received(*, to_email: str, name: str, enquiry_number: str, service_name: str | None):
    subject = f"Enquiry received — {enquiry_number}"
    track_url = _app_url("/track")
    inner = (
        f'<p>Hi {escape(name or "there")},</p>'
        f'<p>Thanks for contacting {escape(_BRAND)}. Your enquiry has been received '
        f'and our team will respond within one business day.</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="background:#f8f9fa;border:1px solid #e5e7eb;padding:14px 18px;margin:14px 0">'
        f'<tr><td style="font-size:13px"><b>Reference:</b> {escape(enquiry_number)}<br>'
        f'{f"<b>Service:</b> {escape(service_name)}<br>" if service_name else ""}'
        f'</td></tr></table>'
        f'<p>Please keep this reference for follow-up.</p>'
        f'{_button(track_url, "Visit ZEROAXIS") if track_url else ""}'
    )
    _bg_send(to=to_email, subject=subject, html=_wrap(inner))


def enquiry_response(*, to_email: str, name: str, enquiry_number: str, response_text: str):
    subject = f"Response to your enquiry — {enquiry_number}"
    # Response text is admin-typed (server actor) but we still escape it.
    inner = (
        f'<p>Hi {escape(name or "there")},</p>'
        f'<p>Our team has responded to your enquiry <b>{escape(enquiry_number)}</b>:</p>'
        f'<blockquote style="border-left:3px solid #00509E;margin:12px 0;padding:8px 14px;'
        f'background:#f8f9fa;font-size:13px;color:#0A1128">{escape(response_text)}</blockquote>'
        f'<p>Reply to this email if you have more questions.</p>'
    )
    _bg_send(to=to_email, subject=subject, html=_wrap(inner))


def order_created(*, to_email: str, name: str, order_number: str, service_name: str, amount: float):
    subject = f"Order created — {order_number}"
    dash_url = _app_url("/dashboard/orders")
    inner = (
        f'<p>Hi {escape(name or "there")},</p>'
        f'<p>Your order has been created. Please complete the payment to proceed.</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="background:#f8f9fa;border:1px solid #e5e7eb;padding:14px 18px;margin:14px 0">'
        f'<tr><td style="font-size:13px">'
        f'<b>Order:</b> {escape(order_number)}<br>'
        f'<b>Service:</b> {escape(service_name)}<br>'
        f'<b>Amount:</b> ₹{amount:,.0f}</td></tr></table>'
        f'{_button(dash_url, "Open your dashboard") if dash_url else ""}'
    )
    _bg_send(to=to_email, subject=subject, html=_wrap(inner))


def payment_submitted(*, to_email: str, name: str, order_number: str, amount: float, reference: str):
    subject = f"Payment submitted — {order_number}"
    inner = (
        f'<p>Hi {escape(name or "there")},</p>'
        f'<p>We have received your payment submission for order '
        f'<b>{escape(order_number)}</b>. It is now pending verification by our team.</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="background:#f8f9fa;border:1px solid #e5e7eb;padding:14px 18px;margin:14px 0">'
        f'<tr><td style="font-size:13px">'
        f'<b>Amount:</b> ₹{amount:,.0f}<br>'
        f'<b>Reference:</b> {escape(reference)}</td></tr></table>'
        f'<p>You will receive another email once the payment is verified.</p>'
    )
    _bg_send(to=to_email, subject=subject, html=_wrap(inner))


def payment_verified(*, to_email: str, name: str, order_number: str, amount: float):
    subject = f"Payment verified — {order_number}"
    dash_url = _app_url("/dashboard/orders")
    inner = (
        f'<p>Hi {escape(name or "there")},</p>'
        f'<p>Your payment for order <b>{escape(order_number)}</b> has been verified. '
        f'Work will begin as scheduled.</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="background:#f8f9fa;border:1px solid #e5e7eb;padding:14px 18px;margin:14px 0">'
        f'<tr><td style="font-size:13px"><b>Amount:</b> ₹{amount:,.0f}</td></tr></table>'
        f'<p>An invoice PDF is now available for download from your dashboard.</p>'
        f'{_button(dash_url, "Download invoice") if dash_url else ""}'
    )
    _bg_send(to=to_email, subject=subject, html=_wrap(inner))


def password_reset(*, to_email: str, name: str, reset_token: str):
    subject = "Reset your ZEROAXIS password"
    reset_url = _app_url(f"/login?reset_token={reset_token}")
    inner = (
        f'<p>Hi {escape(name or "there")},</p>'
        f'<p>We received a request to reset the password for your ZEROAXIS account.</p>'
        f'<p>This link is valid for <b>30 minutes</b> and can only be used once.</p>'
        f'{_button(reset_url, "Reset your password") if reset_url else ""}'
        f'<p style="font-size:12px;color:#6B7280;margin-top:16px">'
        f'If you did not request this, you can safely ignore this email.</p>'
    )
    _bg_send(to=to_email, subject=subject, html=_wrap(inner))


def payment_rejected(*, to_email: str, name: str, order_number: str, note: str):
    subject = f"Payment rejected — {order_number}"
    inner = (
        f'<p>Hi {escape(name or "there")},</p>'
        f'<p>Your payment for order <b>{escape(order_number)}</b> could not be verified.</p>'
        f'{f"<p><b>Reason:</b> {escape(note)}</p>" if note else ""}'
        f'<p>Please resubmit the correct payment reference from your dashboard.</p>'
    )
    _bg_send(to=to_email, subject=subject, html=_wrap(inner))


def payment_reminder(*, to_email: str, name: str, order_number: str, amount: float,
                      days_since_created: int, previously_rejected: bool = False):
    subject = f"Reminder: complete payment for order {order_number}"
    dash_url = _app_url("/dashboard/orders")
    lead = (
        "Your previous payment was not verified. Please resubmit the correct payment reference."
        if previously_rejected else
        f"Just a gentle reminder that your order was created {days_since_created} day(s) ago and the payment is still pending. Please complete it so we can begin the work."
    )
    inner = (
        f'<p>Hi {escape(name or "there")},</p>'
        f'<p>{lead}</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="background:#f8f9fa;border:1px solid #e5e7eb;padding:14px 18px;margin:14px 0">'
        f'<tr><td style="font-size:13px">'
        f'<b>Order:</b> {escape(order_number)}<br>'
        f'<b>Amount due:</b> ₹{amount:,.0f}</td></tr></table>'
        f'{_button(dash_url, "Open your dashboard") if dash_url else ""}'
        f'<p style="font-size:12px;color:#6B7280;margin-top:12px">If you have already paid and are waiting on verification, please ignore this message.</p>'
    )
    _bg_send(to=to_email, subject=subject, html=_wrap(inner))


def status_changed(*, to_email: str, name: str, order_number: str, new_status: str, note: str):
    subject = f"Order status updated — {order_number}"
    label = new_status.replace("_", " ").title()
    inner = (
        f'<p>Hi {escape(name or "there")},</p>'
        f'<p>Order <b>{escape(order_number)}</b> is now <b>{escape(label)}</b>.</p>'
        f'{f"<p>{escape(note)}</p>" if note else ""}'
    )
    _bg_send(to=to_email, subject=subject, html=_wrap(inner))
