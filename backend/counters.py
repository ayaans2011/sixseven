from datetime import datetime, timezone
from database import get_db


async def next_number(name: str, year: int) -> str:
    """Atomically increment counter for name+year and return zero-padded string."""
    db = get_db()
    key = f"{name}:{year}"
    res = await db.counters.find_one_and_update(
        {"name": key},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=True,
    )
    seq = res["seq"] if res else 1
    if seq is None:
        # First insertion returned pre-inc None doc
        seq = 1
    return f"{seq:06d}"


async def generate_enquiry_number() -> str:
    year = datetime.now(timezone.utc).year
    seq = await next_number("enquiry", year)
    return f"ENQ-{year}-{seq}"


async def generate_order_number() -> str:
    year = datetime.now(timezone.utc).year
    seq = await next_number("order", year)
    return f"ZAX-{year}-{seq}"


async def generate_tracking_number() -> str:
    # Same as order number in this app
    return await generate_order_number()
