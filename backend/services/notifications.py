from datetime import datetime, timezone

from database import get_db


async def notify_user(user_id: str | None, title: str, body: str, *, now: str | None = None):
    if not user_id:
        return
    db = get_db()
    await db.notifications.insert_one({
        "user_id": user_id,
        "title": title,
        "body": body,
        "read": False,
        "created_at": now or datetime.now(timezone.utc).isoformat(),
    })


async def notify_admins(title: str, body: str, *, exclude_id: str | None = None, now: str | None = None):
    db = get_db()
    admins = await db.users.find({"role": "admin", "disabled": {"$ne": True}}, {"_id": 1}).to_list(1000)
    ts = now or datetime.now(timezone.utc).isoformat()
    docs = [
        {"user_id": str(a["_id"]), "title": title, "body": body, "read": False, "created_at": ts}
        for a in admins if str(a["_id"]) != exclude_id
    ]
    if docs:
        await db.notifications.insert_many(docs)
