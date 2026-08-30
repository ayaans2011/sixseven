"""Reports & cron endpoints."""
import os
import hmac
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Depends, Request, BackgroundTasks
from html import escape

from database import get_db
from security import require_admin, audit_log
from services import email as email_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["reports"])


async def _generate_report(period_days: int = 30) -> dict:
    """Aggregate report stats for the last N days."""
    db = get_db()
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=period_days)).isoformat()
    since_prev = (now - timedelta(days=period_days * 2)).isoformat()

    orders_period = await db.orders.find({"created_at": {"$gte": since}}).to_list(5000)
    orders_prev = await db.orders.find(
        {"created_at": {"$gte": since_prev, "$lt": since}}
    ).to_list(5000)

    verified_orders = [o for o in orders_period if o.get("payment_status") == "PAYMENT_VERIFIED"]
    pending = [o for o in orders_period if o.get("payment_status") == "PENDING_VERIFICATION"]
    completed = [o for o in orders_period if o.get("order_status") == "COMPLETED"]

    revenue = sum(float(o.get("amount", 0) or 0) for o in verified_orders)
    prev_revenue = sum(float(o.get("amount", 0) or 0)
                       for o in orders_prev if o.get("payment_status") == "PAYMENT_VERIFIED")

    new_enquiries = await db.enquiries.count_documents({"created_at": {"$gte": since}})
    new_customers = await db.users.count_documents(
        {"role": "customer", "created_at": {"$gte": since}}
    )

    top_services: dict[str, dict] = {}
    for o in verified_orders:
        sname = o.get("service_name", "Unknown")
        top_services.setdefault(sname, {"count": 0, "revenue": 0.0})
        top_services[sname]["count"] += 1
        top_services[sname]["revenue"] += float(o.get("amount", 0) or 0)
    top_list = sorted(
        [{"name": k, **v} for k, v in top_services.items()],
        key=lambda x: x["revenue"], reverse=True,
    )[:5]

    return {
        "period_start": since,
        "period_end": now.isoformat(),
        "period_days": period_days,
        "total_orders": len(orders_period),
        "verified_orders": len(verified_orders),
        "pending_payments": len(pending),
        "completed_orders": len(completed),
        "revenue": revenue,
        "previous_revenue": prev_revenue,
        "revenue_change_pct": ((revenue - prev_revenue) / prev_revenue * 100) if prev_revenue else None,
        "new_enquiries": new_enquiries,
        "new_customers": new_customers,
        "top_services": top_list,
    }


def _report_html(r: dict, title: str) -> str:
    def money(v): return f"₹{float(v or 0):,.0f}"
    chg = ""
    if r.get("revenue_change_pct") is not None:
        arrow = "▲" if r["revenue_change_pct"] >= 0 else "▼"
        chg = f' <span style="color:{"#146C2E" if r["revenue_change_pct"] >=0 else "#A11B1B"}">{arrow} {abs(r["revenue_change_pct"]):.1f}% vs prev period</span>'
    rows = "".join(
        f'<tr><td style="padding:6px 10px;border-bottom:1px solid #E5E7EB">{escape(s["name"])}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;text-align:right">{s["count"]}</td>'
        f'<td style="padding:6px 10px;border-bottom:1px solid #E5E7EB;text-align:right">{money(s["revenue"])}</td></tr>'
        for s in r.get("top_services", [])
    ) or '<tr><td colspan="3" style="padding:12px;color:#6B7280;text-align:center">No verified orders in this period.</td></tr>'

    period = f"{r['period_start'][:10]} → {r['period_end'][:10]}"
    inner = (
        f'<p style="margin:0 0 12px">Summary for <b>{escape(period)}</b> ({r["period_days"]} days).</p>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border-collapse:collapse">'
        f'<tr>'
        f'<td style="padding:12px;background:#F8F9FA;border:1px solid #E5E7EB;width:33%">'
        f'<div style="font-size:11px;color:#6B7280;text-transform:uppercase">Revenue (verified)</div>'
        f'<div style="font-size:22px;font-weight:700;color:#0A1128">{money(r["revenue"])}</div>{chg}</td>'
        f'<td style="padding:12px;background:#F8F9FA;border:1px solid #E5E7EB;border-left:0;width:33%">'
        f'<div style="font-size:11px;color:#6B7280;text-transform:uppercase">Verified orders</div>'
        f'<div style="font-size:22px;font-weight:700;color:#0A1128">{r["verified_orders"]}</div></td>'
        f'<td style="padding:12px;background:#F8F9FA;border:1px solid #E5E7EB;border-left:0">'
        f'<div style="font-size:11px;color:#6B7280;text-transform:uppercase">Pending payments</div>'
        f'<div style="font-size:22px;font-weight:700;color:#0A1128">{r["pending_payments"]}</div></td>'
        f'</tr>'
        f'<tr>'
        f'<td style="padding:12px;background:#F8F9FA;border:1px solid #E5E7EB;border-top:0">'
        f'<div style="font-size:11px;color:#6B7280;text-transform:uppercase">Completed</div>'
        f'<div style="font-size:22px;font-weight:700;color:#0A1128">{r["completed_orders"]}</div></td>'
        f'<td style="padding:12px;background:#F8F9FA;border:1px solid #E5E7EB;border-top:0;border-left:0">'
        f'<div style="font-size:11px;color:#6B7280;text-transform:uppercase">New enquiries</div>'
        f'<div style="font-size:22px;font-weight:700;color:#0A1128">{r["new_enquiries"]}</div></td>'
        f'<td style="padding:12px;background:#F8F9FA;border:1px solid #E5E7EB;border-top:0;border-left:0">'
        f'<div style="font-size:11px;color:#6B7280;text-transform:uppercase">New customers</div>'
        f'<div style="font-size:22px;font-weight:700;color:#0A1128">{r["new_customers"]}</div></td>'
        f'</tr></table>'
        f'<h3 style="margin:22px 0 8px;color:#0A1128">Top services</h3>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%" style="border:1px solid #E5E7EB;border-collapse:collapse">'
        f'<tr style="background:#F8F9FA"><th align="left" style="padding:6px 10px;border-bottom:1px solid #E5E7EB">Service</th>'
        f'<th align="right" style="padding:6px 10px;border-bottom:1px solid #E5E7EB">Orders</th>'
        f'<th align="right" style="padding:6px 10px;border-bottom:1px solid #E5E7EB">Revenue</th></tr>'
        f'{rows}</table>'
    )
    # Reuse email service _wrap for consistent branding
    return email_svc._wrap(inner)  # type: ignore[attr-defined]


async def _send_report_email():
    r = await _generate_report(30)
    to_email = os.environ.get("REPORT_TO_EMAIL") or os.environ.get("OWNER_EMAIL") or os.environ.get("ADMIN_EMAIL")
    if not to_email:
        logger.warning("No REPORT_TO_EMAIL configured — skipping monthly report send")
        return
    subject = f"ZEROAXIS Monthly Report — {r['period_end'][:10]}"
    html = _report_html(r, subject)
    # Bypass background helper and await directly so we can log the id
    email_id = await email_svc._send_email(to=to_email, subject=subject, html=html)  # type: ignore
    logger.info(f"Monthly report email dispatched: id={email_id} to={to_email}")


# Admin: preview the current report as JSON
@router.get("/reports/monthly")
async def monthly_report(admin=Depends(require_admin), days: int = 30):
    r = await _generate_report(days)
    return r


# Admin: force-send the report email now (for testing / manual runs)
@router.post("/reports/monthly/send")
async def monthly_report_send(background: BackgroundTasks, admin=Depends(require_admin)):
    background.add_task(_send_report_email)
    await audit_log("monthly_report_manual_send", admin["id"], admin["email"], "report", "monthly")
    return {"success": True, "message": "Report queued for delivery."}


# Cron endpoint — MUST return 2xx immediately; do the work in the background.
@router.post("/cron/monthly-report")
async def cron_monthly_report(request: Request, background: BackgroundTasks):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    expected = os.environ.get("WEBHOOK_CRON_SECRET", "")
    auth = request.headers.get("Authorization", "")
    if not expected or not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Unauthorized")
    if not hmac.compare_digest(auth[7:], expected):
        raise HTTPException(status_code=401, detail="Unauthorized")

    run_id = request.headers.get("X-Webhook-Id")
    if run_id:
        db = get_db()
        seen = await db.cron_runs.find_one({"run_id": run_id})
        if seen:
            return {"ok": True, "duplicate": True}
        await db.cron_runs.insert_one({
            "run_id": run_id, "job": "monthly-report",
            "at": datetime.now(timezone.utc).isoformat(),
        })
    background.add_task(_send_report_email)
    return {"ok": True}
