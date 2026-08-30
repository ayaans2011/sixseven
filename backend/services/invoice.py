"""Invoice PDF generation using reportlab."""
from io import BytesIO
from datetime import datetime, timezone
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.pdfgen import canvas


NAVY = colors.HexColor("#0A1128")
ACCENT = colors.HexColor("#00509E")
MUTED = colors.HexColor("#6B7280")
LINE = colors.HexColor("#E5E7EB")


def _fmt_date(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b %Y")
    except Exception:
        return iso[:10]


def generate_invoice_pdf(*, order: dict, customer: dict, content: dict) -> bytes:
    """Return an A4 PDF invoice as bytes."""
    business = content.get("about", {}) if isinstance(content, dict) else {}
    contact = content.get("contact", {}) if isinstance(content, dict) else {}
    udyam = content.get("udyam", {}) if isinstance(content, dict) else {}
    programmer = content.get("programmer", {}) if isinstance(content, dict) else {}

    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # ---- Header band ----
    c.setFillColor(NAVY)
    c.rect(0, H - 30 * mm, W, 30 * mm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(18 * mm, H - 15 * mm, "ZEROAXIS")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#94A3B8"))
    c.drawString(18 * mm, H - 20 * mm, "Technology & Digital Services")
    c.drawString(18 * mm, H - 24 * mm, f"Established {business.get('established','2020')} · "
                                        f"{business.get('experience_years','5')} years experience")

    # Invoice title (right side)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 18)
    c.drawRightString(W - 18 * mm, H - 15 * mm, "INVOICE")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#94A3B8"))
    c.drawRightString(W - 18 * mm, H - 20 * mm, f"# {order.get('order_number','')}")
    c.drawRightString(W - 18 * mm, H - 24 * mm, f"Date: {_fmt_date(order.get('updated_at') or order.get('created_at'))}")

    # ---- From / To ----
    y = H - 42 * mm
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(18 * mm, y, "FROM")
    c.drawString(110 * mm, y, "BILL TO")
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(18 * mm, y - 2, W - 18 * mm, y - 2)

    y -= 8 * mm
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(18 * mm, y, "ZEROAXIS")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#1F2937"))
    lines_from = [
        f"Main Programmer: {programmer.get('name','Ayaan')}",
        contact.get("address", "[YOUR ADDRESS]"),
        f"Phone: {contact.get('phone','[YOUR PHONE]')}",
        f"Email: {contact.get('email','[YOUR EMAIL]')}",
        f"Udyam / MSME: {udyam.get('number','[UDYAM-XX-XX-XXXXXXX]')}",
    ]
    for line in lines_from:
        y -= 5 * mm
        c.drawString(18 * mm, y, str(line))

    y2 = H - 50 * mm
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(NAVY)
    c.drawString(110 * mm, y2, customer.get("name") or order.get("customer_name") or "Customer")
    c.setFont("Helvetica", 9)
    c.setFillColor(colors.HexColor("#1F2937"))
    lines_to = [
        customer.get("email") or order.get("customer_email") or "",
        customer.get("phone") or "",
        customer.get("company") or "",
        customer.get("address") or "",
    ]
    for line in [l for l in lines_to if l]:
        y2 -= 5 * mm
        c.drawString(110 * mm, y2, str(line))

    # ---- Line items table ----
    ty = min(y, y2) - 14 * mm
    c.setFillColor(colors.HexColor("#F8F9FA"))
    c.rect(18 * mm, ty - 6 * mm, W - 36 * mm, 8 * mm, stroke=0, fill=1)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, ty - 3 * mm, "Description")
    c.drawRightString(W - 60 * mm, ty - 3 * mm, "Qty")
    c.drawRightString(W - 40 * mm, ty - 3 * mm, "Rate")
    c.drawRightString(W - 20 * mm, ty - 3 * mm, "Amount")

    ty -= 12 * mm
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    amount = float(order.get("amount", 0) or 0)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 10.5)
    c.drawString(20 * mm, ty, order.get("service_name", "Service"))
    req = (order.get("requirement") or "").strip()
    if req:
        c.setFont("Helvetica", 9)
        c.setFillColor(MUTED)
        # Wrap requirement to ~90 chars per line
        rline = req[:90]
        c.drawString(20 * mm, ty - 4.5 * mm, rline)
        if len(req) > 90:
            c.drawString(20 * mm, ty - 9 * mm, req[90:180])
    c.setFillColor(NAVY)
    c.setFont("Helvetica", 10)
    c.drawRightString(W - 60 * mm, ty, "1")
    c.drawRightString(W - 40 * mm, ty, f"₹{amount:,.2f}")
    c.drawRightString(W - 20 * mm, ty, f"₹{amount:,.2f}")

    ty -= 18 * mm
    c.line(18 * mm, ty, W - 18 * mm, ty)

    # ---- Totals ----
    ty -= 8 * mm
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 10)
    c.drawRightString(W - 40 * mm, ty, "Subtotal")
    c.setFillColor(NAVY)
    c.drawRightString(W - 20 * mm, ty, f"₹{amount:,.2f}")

    ty -= 6 * mm
    c.setFillColor(MUTED)
    c.drawRightString(W - 40 * mm, ty, "Tax")
    c.setFillColor(NAVY)
    c.drawRightString(W - 20 * mm, ty, "₹0.00")

    ty -= 8 * mm
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.8)
    c.line(120 * mm, ty + 2 * mm, W - 18 * mm, ty + 2 * mm)
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(W - 40 * mm, ty - 3 * mm, "Total")
    c.setFillColor(ACCENT)
    c.drawRightString(W - 20 * mm, ty - 3 * mm, f"₹{amount:,.2f}")

    # ---- Payment status ----
    ty -= 20 * mm
    c.setFillColor(colors.HexColor("#E7F5EA"))
    c.rect(18 * mm, ty - 4 * mm, 60 * mm, 8 * mm, stroke=0, fill=1)
    c.setFillColor(colors.HexColor("#146C2E"))
    c.setFont("Helvetica-Bold", 10)
    status = (order.get("payment_status") or "UNPAID").replace("_", " ")
    c.drawString(22 * mm, ty - 1 * mm, f"Payment: {status}")

    # ---- Footer ----
    c.setStrokeColor(LINE)
    c.setLineWidth(0.5)
    c.line(18 * mm, 22 * mm, W - 18 * mm, 22 * mm)
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 8.5)
    c.drawString(18 * mm, 17 * mm, "Thank you for choosing ZEROAXIS. This is a computer-generated invoice.")
    c.drawString(18 * mm, 13 * mm,
                 f"Tracking: {order.get('tracking_number','-')}  ·  "
                 f"Generated: {datetime.now(timezone.utc).strftime('%d %b %Y %H:%M UTC')}")
    if udyam.get("registered"):
        c.drawString(18 * mm, 9 * mm, f"Udyam Registered: {udyam.get('number','')}")

    c.showPage()
    c.save()
    return buf.getvalue()
