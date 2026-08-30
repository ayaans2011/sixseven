from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Depends
from bson import ObjectId

from database import get_db
from security import get_current_user, require_admin, audit_log
from models import ServiceIn, ServiceUpdate

router = APIRouter(prefix="/api/services", tags=["services"])


def _serialize(s: dict) -> dict:
    return {
        "id": str(s["_id"]),
        "name": s["name"],
        "slug": s["slug"],
        "description": s.get("description", ""),
        "price": s.get("price", 0),
        "category": s.get("category", "General"),
        "active": s.get("active", True),
        "created_at": s.get("created_at"),
    }


@router.get("")
async def list_services(active_only: bool = True):
    db = get_db()
    q = {"active": True} if active_only else {}
    items = await db.services.find(q).sort("name", 1).to_list(200)
    return [_serialize(s) for s in items]


@router.get("/{sid}")
async def get_service(sid: str):
    db = get_db()
    try:
        s = await db.services.find_one({"_id": ObjectId(sid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Service not found")
    if not s:
        raise HTTPException(status_code=404, detail="Service not found")
    return _serialize(s)


@router.post("")
async def create_service(data: ServiceIn, admin=Depends(require_admin)):
    db = get_db()
    if await db.services.find_one({"slug": data.slug}):
        raise HTTPException(status_code=400, detail="Slug already used")
    doc = data.model_dump()
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.services.insert_one(doc)
    await audit_log("service_created", admin["id"], admin["email"], "service", str(res.inserted_id), {"name": data.name})
    doc["_id"] = res.inserted_id
    return _serialize(doc)


@router.put("/{sid}")
async def update_service(sid: str, data: ServiceUpdate, admin=Depends(require_admin)):
    db = get_db()
    update = {k: v for k, v in data.model_dump().items() if v is not None}
    if not update:
        raise HTTPException(status_code=400, detail="Nothing to update")
    try:
        res = await db.services.update_one({"_id": ObjectId(sid)}, {"$set": update})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Not found")
    await audit_log("service_updated", admin["id"], admin["email"], "service", sid, update)
    doc = await db.services.find_one({"_id": ObjectId(sid)})
    return _serialize(doc)


@router.delete("/{sid}")
async def delete_service(sid: str, admin=Depends(require_admin)):
    db = get_db()
    try:
        await db.services.delete_one({"_id": ObjectId(sid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    await audit_log("service_deleted", admin["id"], admin["email"], "service", sid)
    return {"success": True}
