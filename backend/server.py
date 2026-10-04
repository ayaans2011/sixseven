import os
import logging
from pathlib import Path
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from datetime import datetime, timezone

from database import get_db, ensure_indexes, close_db
from security import hash_password, verify_password
from routes.auth import router as auth_router
from routes.admin_auth import router as admin_auth_router
from routes.services import router as services_router
from routes.enquiries import router as enquiries_router
from routes.orders import router as orders_router
from routes.notifications import router as notif_router
from routes.admin import router as admin_router
from routes.files import router as files_router
from routes.messages import router as messages_router
from routes.reports import router as reports_router
from routes.support import router as support_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("zeroaxis")

app = FastAPI(title="ZEROAXIS API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=[origin.strip() for origin in os.environ.get("CORS_ORIGINS", "https://sixseven-frontend.onrender.com").split(",") if origin.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(admin_auth_router)
app.include_router(services_router)
app.include_router(enquiries_router)
app.include_router(orders_router)
app.include_router(notif_router)
app.include_router(admin_router)
app.include_router(files_router)
app.include_router(messages_router)
app.include_router(reports_router)
app.include_router(support_router)


@app.get("/api/")
async def root():
    return {"service": "ZEROAXIS", "status": "ok"}


@app.get("/api/health")
async def health():
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


async def _seed_admin(email: str, password: str, name: str):
    db = get_db()
    email = email.lower().strip()
    existing = await db.users.find_one({"email": email})
    if existing is None:
        await db.users.insert_one({
            "email": email,
            "password_hash": hash_password(password),
            "name": name,
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
        logger.info(f"Seeded admin: {email}")
    else:
        updates = {}
        if not verify_password(password, existing["password_hash"]):
            updates["password_hash"] = hash_password(password)
        if existing.get("role") != "admin":
            updates["role"] = "admin"
        if updates:
            await db.users.update_one({"_id": existing["_id"]}, {"$set": updates})
            logger.info(f"Updated admin: {email}")


async def _seed_default_content():
    db = get_db()
    defaults = {
        "hero": {"tagline": "Established Technology & Digital Services","headline": "Reliable technology work, delivered the traditional way.","subtext": "Zeroaxis provides technology and digital services with a focus on quality, accountability and long-term reliability."},
        "about": {"title": "About Zeroaxis","body": "Zeroaxis is a technology and digital services company. We work with clients to deliver software, digital solutions and technical support. Our approach is straightforward: understand the requirement, do the work properly, and deliver on schedule.","experience_years": "5","established": "2020"},
        "programmer": {"name": "Ayaan","title": "Main Programmer","bio": "Ayaan leads the technical work at Zeroaxis and is responsible for the majority of the programming and delivery. He brings hands-on experience across software development and technical problem-solving."},
        "udyam": {"registered": False,"number": "[UDYAM-XX-XX-XXXXXXX]","note": "Official Udyam/MSME registration details will be displayed here once verified."},
        "contact": {"email": "[YOUR EMAIL]","phone": "[YOUR PHONE]","address": "[YOUR ADDRESS]","hours": "Monday – Saturday, 10:00 – 19:00"},
        "why": {"points": ["5+ years of practical technology experience","Direct communication with the person doing the work","Transparent order tracking and payment verification","Straightforward pricing and clear timelines","Accountable end-to-end delivery"]},
        "announcement": {"text": "", "active": False},
    }
    for key, value in defaults.items():
        if not await db.content.find_one({"key": key}):
            await db.content.insert_one({"key": key, "value": value, "updated_at": datetime.now(timezone.utc).isoformat()})


async def _seed_default_services():
    db = get_db()
    if await db.services.count_documents({}) > 0:
        return
    items = [
        {"name": "Website Development", "slug": "website-development","description": "Custom websites — corporate, portfolio, informational sites with clean design and reliable hosting guidance.","price": 12000, "category": "Web", "active": True},
        {"name": "Web Application Development", "slug": "web-application","description": "Full-stack web applications with authentication, database, admin panel and role-based access.","price": 35000, "category": "Web", "active": True},
        {"name": "Mobile-Friendly Landing Page", "slug": "landing-page","description": "Single-page marketing website with contact form and mobile responsive design.","price": 5000, "category": "Web", "active": True},
        {"name": "Bug Fixing & Maintenance", "slug": "bug-fix","description": "Fix bugs, patch issues and maintain existing websites or applications on a per-task basis.","price": 2500, "category": "Support", "active": True},
        {"name": "Custom Software / Automation", "slug": "custom-software","description": "Automation scripts, custom tools and internal software tailored to specific business needs.","price": 20000, "category": "Software", "active": True},
        {"name": "Technical Consulting", "slug": "consulting","description": "Advisory sessions on architecture, stack selection, security or project planning.","price": 3000, "category": "Advisory", "active": True},
    ]
    now = datetime.now(timezone.utc).isoformat()
    for it in items:
        it["created_at"] = now
    await db.services.insert_many(items)


@app.on_event("startup")
async def startup():
    await ensure_indexes()
    try:
        from routes.files import init_storage
        key = init_storage()
        if key:
            logger.info("Object storage initialized")
        else:
            logger.warning("Object storage not initialized — file uploads will 503 until fixed")
    except Exception as e:
        logger.error(f"Storage init error: {e}")
    await _seed_admin(os.environ.get("ADMIN_EMAIL", "admin@zeroaxis.in"), os.environ.get("ADMIN_PASSWORD", "admin123"), "Zeroaxis Admin")
    owner_email = os.environ.get("OWNER_EMAIL")
    owner_password = os.environ.get("OWNER_PASSWORD")
    if owner_email and owner_password:
        await _seed_admin(owner_email, owner_password, "Ayaan (Owner)")
    await _seed_default_content()
    await _seed_default_services()
    logger.info("ZEROAXIS backend started")


@app.on_event("shutdown")
async def shutdown():
    await close_db()
