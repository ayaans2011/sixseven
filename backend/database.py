import os
from motor.motor_asyncio import AsyncIOMotorClient

_client: AsyncIOMotorClient | None = None
_db = None


def get_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    return _client


def get_db():
    global _db
    if _db is None:
        _db = get_client()[os.environ["DB_NAME"]]
    return _db


async def close_db():
    global _client
    if _client is not None:
        _client.close()
        _client = None


async def ensure_indexes():
    db = get_db()
    await db.users.create_index("email", unique=True)
    await db.login_attempts.create_index("identifier")
    await db.password_reset_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.registration_email_otps.create_index("expires_at", expireAfterSeconds=0)
    await db.account_activation_tokens.create_index("expires_at", expireAfterSeconds=0)
    await db.admin_login_challenges.create_index("expires_at", expireAfterSeconds=0)
    await db.services.create_index("slug", unique=True)
    await db.enquiries.create_index("enquiry_number", unique=True)
    await db.enquiries.create_index("customer_id")
    await db.orders.create_index("order_number", unique=True)
    await db.orders.create_index("tracking_number", unique=True)
    await db.orders.create_index("customer_id")
    await db.order_status_history.create_index("order_id")
    await db.payments.create_index("order_id")
    await db.notifications.create_index("user_id")
    await db.audit_logs.create_index("timestamp")
    await db.content.create_index("key", unique=True)
    await db.counters.create_index("name", unique=True)
