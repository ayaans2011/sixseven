# ZEROAXIS — Product Requirements

## Original problem statement
Build a classic, established, professional technology business website (ZEROAXIS) with a strong, structured backend. Not a flashy SaaS. Prioritize security, backend correctness and DB integrity over visual effects. Manual payment verification. Roles: admin & customer. Track orders (ZAX-YYYY-NNNNNN), enquiries (ENQ-YYYY-NNNNNN). Udyam/MSME placeholder editable via CMS. Main Programmer: Ayaan. 5 years experience.

## Architecture
- **Backend**: FastAPI + MongoDB (motor). Modular routers under /app/backend/routes: auth, services, enquiries, orders, notifications, admin. Central security.py (bcrypt + JWT HttpOnly cookies + Bearer fallback, 5-attempt lockout for 15min, audit_log helper). counters.py for atomic ENQ / ZAX number generation. Database indexes on startup.
- **Frontend**: React + Tailwind + Shadcn. Merriweather + IBM Plex Sans fonts. Classic layout, single accent (#00509E). Sonner toasts.
- **Auth**: JWT custom, 12h access + 7d refresh, HttpOnly + secure + SameSite=None cookies; Bearer fallback for cross-origin.
- **Roles**: `admin` and `customer`. Admin seeded on startup from .env.

## User personas
- **Visitor**: browses services, submits public enquiry, tracks order by number.
- **Customer**: registers, places orders, submits payment reference, tracks progress, receives notifications.
- **Admin**: manages customers, services, enquiries, orders, verifies payments, uploads payment QR (per-customer default or per-order override), edits website content, sends notifications, views audit logs.

## Core requirements (implemented)
- Homepage with Hero, Services, Why Zeroaxis, About, Programmer, How it works, Udyam placeholder, Contact CTA, Footer
- Pages: Home, About, Services, Enquiry, Track Order, Contact, Login, Register
- Customer dashboard: Overview, Enquiries, Orders (create + submit payment + timeline), Notifications, Profile
- Admin dashboard: Dashboard, Customers (+ per-customer QR upload), Enquiries, Orders (+ per-order QR override, payment verify/reject, status update, timeline), Payments, Services CRUD, Notifications (broadcast + targeted), Website Content (JSON per key), Audit Logs
- Backend endpoints:
  - Auth: `/api/auth/{register,login,logout,me,forgot-password,reset-password}`
  - Services: `/api/services` (public GET), admin POST/PUT/DELETE
  - Enquiries: `/api/enquiries/public`, `/api/enquiries` (auth), `/api/enquiries/mine`, `/api/enquiries/admin/all`, `/api/enquiries/{id}/respond`
  - Orders: `/api/orders`, `/mine`, `/track/{tn}` (public), `/{id}`, `/{id}/payment`, `/{id}/payment/verify`, `/{id}/status`, `/admin/all`, `/{id}/qr`
  - Admin: `/api/admin/{stats,customers,customers/{id}/toggle,customers/{id}/qr,orders/{id}/qr,content,audit-logs,notifications}`, `/api/content`, `/api/notifications`, `/api/users/me`
- Payment lifecycle: UNPAID → PAYMENT_SUBMITTED → PENDING_VERIFICATION → PAYMENT_VERIFIED / PAYMENT_REJECTED
- Order lifecycle: CREATED → PAYMENT_SUBMITTED → PAYMENT_VERIFIED → WORK_STARTED → IN_PROGRESS → READY_FOR_DELIVERY → COMPLETED (with immutable order_status_history)
- Security: bcrypt hashes, HttpOnly cookies, brute-force lockout, ownership checks on every private resource, no ObjectId returned to browser (only str id), admin-only routes guarded, audit log for every important action.
- **Payment QR (added on user request)**: Admin uploads QR image per customer (default) and can optionally override per order. Customer sees the QR + label on the order payment form. Base64 data URL, ≤2MB, image/* only.

## What's been implemented (2026-02)
- Full backend with 40+ endpoints, MongoDB indexes, audit trail, brute-force lockout
- Full classic-business frontend with 9 public routes + customer + admin dashboards
- Seeded admin accounts and 6 default services + editable content keys
- Payment QR upload flow (customer default + order override) with data-URL validation and auth guards
- **Invoice PDFs**: Server-generated A4 invoice using reportlab (`/api/orders/{id}/invoice.pdf`); available for both admin and the owning customer after payment is verified; embeds Udyam number, business address, tracking number and amount from the CMS content keys.
- **Email notifications**: Emergent-managed Resend integration with server-side templates and full guardrail gate (`_assert_safe_email`). Triggers on enquiry received, enquiry response, order created, payment submitted, payment verified, payment rejected and order status changed. Failures never break business flows.
- **File attachments**: Emergent object storage backend (`/api/files/upload|list|download|delete`) with parent ownership check (order or enquiry). MIME + extension whitelist, 10 MB per file. Available in the customer order/enquiry modals and admin order/enquiry modals.
- **Order search + CSV export**: `/api/orders/admin/all` now supports `q` (order#, customer, service), `status`, `payment_status`, `date_from`, `date_to`. New `/api/orders/admin/export.csv` streams a filtered CSV. Admin Orders page has a filter card and Export CSV button.
- **Convert To Order**: Admin can turn any enquiry into a pre-filled order in one tap. If the enquirer had no account, a customer account is auto-created and the order created for them (they can reset password via forgot-password). Enquiry is marked `converted` and linked to the order (`converted_order_id`).
- **Announcement Banner**: A site-wide banner shown at the very top of every page, driven by the `announcement` content key ({ active, text }). Toggle from Admin → Website Content.
- **Customer Chat**: Message threads on every order and every enquiry (`/api/messages` GET/POST). Both customer and admin can post; the "other side's" messages are auto-marked read on view; unread-count endpoint provided. Uses ownership-checked parent auth just like files.
- **Monthly Report**: `/api/reports/monthly` (admin GET) returns aggregated stats (revenue, verified/pending/completed orders, new enquiries/customers, top services with delta vs previous period). `/api/reports/monthly/send` triggers a manual send. `.emergent/crons.yml` schedules a monthly delivery on the 1st of every month at 09:00 IST via `/api/cron/monthly-report` (auth: Bearer WEBHOOK_CRON_SECRET, idempotent via X-Webhook-Id, ack 2xx immediately + BackgroundTasks for the actual send).

## Prioritized backlog
- **P1**: File uploads for enquiries/orders (spec allows), invoices PDF, messages/chat between admin↔customer.
- **P1**: Email notifications (Resend) for enquiry received / payment verified / status changes.
- **P2**: Admin CSV export of orders, customers, audit logs. Search/filter on admin tables.
- **P2**: Password reset via email (currently token is logged to server console).
- **P2**: Invoice generator with company details + Udyam number.
- **P3**: Announcement banner on homepage from the `announcement` content key.

## Test credentials
- Admin: zeroaxis.pvtltd.in@gmail.com / admin123
- Owner admin: ayaanss2011@gmail.com / Ayaan@Zeroaxis1
- Test customer: testcustomer@zeroaxis.in / Test@1234 (auto-created during backend testing; register any new customer via /register)
