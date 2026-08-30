"""File upload endpoints backed by Emergent Object Storage.

Attachments belong to an order or an enquiry. DB (`files` collection) is source of
truth; storage holds the bytes. Soft-delete on remove (storage has no delete API).
"""
import os
import uuid
import mimetypes
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import requests
from bson import ObjectId
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, Query
from fastapi.responses import Response

from database import get_db
from security import get_current_user, audit_log

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/files", tags=["files"])

STORAGE_BASE = (os.environ.get("INTEGRATION_PROXY_URL") or "").strip() or "https://integrations.emergentagent.com"
STORAGE_URL = STORAGE_BASE.rstrip("/") + "/objstore/api/v1/storage"
APP_NAME = "zeroaxis"

_storage_key: str | None = None


def init_storage(force: bool = False) -> str | None:
    """Return a storage_key. Cached. Never raises — returns None on failure."""
    global _storage_key
    if _storage_key and not force:
        return _storage_key
    emergent_key = os.environ.get("EMERGENT_LLM_KEY")
    if not emergent_key:
        logger.warning("EMERGENT_LLM_KEY missing — object storage disabled")
        return None
    try:
        resp = requests.post(f"{STORAGE_URL}/init", json={"emergent_key": emergent_key}, timeout=30)
        resp.raise_for_status()
        _storage_key = resp.json().get("storage_key")
        return _storage_key
    except Exception as e:
        logger.error(f"Storage init failed: {e}")
        return None


def _put(path: str, data: bytes, content_type: str) -> dict:
    key = init_storage()
    if not key:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    resp = requests.put(
        f"{STORAGE_URL}/objects/{path}",
        headers={"X-Storage-Key": key, "Content-Type": content_type},
        data=data, timeout=120,
    )
    if resp.status_code in (403, 404):
        init_storage(force=True)
        key = _storage_key
        if not key:
            raise HTTPException(status_code=503, detail="Storage unavailable")
        resp = requests.put(
            f"{STORAGE_URL}/objects/{path}",
            headers={"X-Storage-Key": key, "Content-Type": content_type},
            data=data, timeout=120,
        )
    resp.raise_for_status()
    return resp.json()


def _get(path: str) -> tuple[bytes, str]:
    key = init_storage()
    if not key:
        raise HTTPException(status_code=503, detail="Storage unavailable")
    resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if resp.status_code in (403, 404):
        init_storage(force=True)
        key = _storage_key
        if not key:
            raise HTTPException(status_code=404, detail="File missing")
        resp = requests.get(f"{STORAGE_URL}/objects/{path}", headers={"X-Storage-Key": key}, timeout=60)
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="File missing")
    resp.raise_for_status()
    return resp.content, resp.headers.get("Content-Type", "application/octet-stream")


ALLOWED_EXT = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif",
               ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".zip"}
ALLOWED_MIME_PREFIXES = ("image/", "application/pdf", "application/msword",
                         "application/vnd.openxmlformats-officedocument",
                         "application/vnd.ms-excel", "text/plain", "text/csv",
                         "application/zip", "application/x-zip-compressed",
                         "application/octet-stream")


def _safe_ext(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return ext if ext in ALLOWED_EXT else ""


async def _load_parent(db, parent_type: str, parent_id: str) -> dict:
    if parent_type not in ("order", "enquiry"):
        raise HTTPException(status_code=400, detail="parent_type must be 'order' or 'enquiry'")
    coll = db.orders if parent_type == "order" else db.enquiries
    try:
        doc = await coll.find_one({"_id": ObjectId(parent_id)})
    except Exception:
        raise HTTPException(status_code=404, detail="Parent not found")
    if not doc:
        raise HTTPException(status_code=404, detail="Parent not found")
    return doc


def _can_access(user: dict, parent: dict) -> bool:
    if user["role"] == "admin":
        return True
    return parent.get("customer_id") == user["id"]


@router.post("/upload")
async def upload_file(
    parent_type: Literal["order", "enquiry"] = Form(...),
    parent_id: str = Form(...),
    note: str = Form(""),
    file: UploadFile = File(...),
    user=Depends(get_current_user),
):
    db = get_db()
    parent = await _load_parent(db, parent_type, parent_id)
    if not _can_access(user, parent):
        raise HTTPException(status_code=403, detail="Forbidden")

    ext = _safe_ext(file.filename or "")
    if not ext:
        raise HTTPException(status_code=400, detail="File type not allowed")

    max_mb = int(os.environ.get("MAX_UPLOAD_MB", "10"))
    contents = await file.read()
    if len(contents) > max_mb * 1024 * 1024:
        raise HTTPException(status_code=400, detail=f"File too large (max {max_mb}MB)")
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file")

    mime = file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream"
    if not any(mime.startswith(p) for p in ALLOWED_MIME_PREFIXES):
        raise HTTPException(status_code=400, detail=f"MIME type not allowed: {mime}")

    storage_path = f"{APP_NAME}/uploads/{user['id']}/{uuid.uuid4().hex}{ext}"
    try:
        result = await asyncio.to_thread(_put, storage_path, contents, mime)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload failed: {e}")
        raise HTTPException(status_code=502, detail="Upload failed")

    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "parent_type": parent_type,
        "parent_id": parent_id,
        "owner_id": user["id"],
        "owner_email": user["email"],
        "original_name": (file.filename or "file")[:200],
        "storage_path": result.get("path") or storage_path,
        "size": result.get("size", len(contents)),
        "mime": mime,
        "note": (note or "")[:500],
        "is_deleted": False,
        "created_at": now,
    }
    res = await db.files.insert_one(doc)
    await audit_log("file_uploaded", user["id"], user["email"], parent_type, parent_id,
                    {"file_id": str(res.inserted_id), "name": doc["original_name"], "size": doc["size"]})
    return {
        "id": str(res.inserted_id),
        "original_name": doc["original_name"],
        "size": doc["size"],
        "mime": doc["mime"],
        "note": doc["note"],
        "created_at": doc["created_at"],
        "owner_email": doc["owner_email"],
    }


@router.get("/list")
async def list_files(parent_type: str = Query(...), parent_id: str = Query(...),
                     user=Depends(get_current_user)):
    db = get_db()
    parent = await _load_parent(db, parent_type, parent_id)
    if not _can_access(user, parent):
        raise HTTPException(status_code=403, detail="Forbidden")
    items = await db.files.find(
        {"parent_type": parent_type, "parent_id": parent_id, "is_deleted": {"$ne": True}}
    ).sort("created_at", -1).to_list(200)
    return [{
        "id": str(f["_id"]),
        "original_name": f["original_name"],
        "size": f["size"],
        "mime": f.get("mime"),
        "note": f.get("note", ""),
        "created_at": f.get("created_at"),
        "owner_email": f.get("owner_email"),
    } for f in items]


@router.get("/{fid}/download")
async def download_file(fid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        f = await db.files.find_one({"_id": ObjectId(fid), "is_deleted": {"$ne": True}})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    parent = await _load_parent(db, f["parent_type"], f["parent_id"])
    if not _can_access(user, parent):
        raise HTTPException(status_code=403, detail="Forbidden")
    try:
        content, ctype = await asyncio.to_thread(_get, f["storage_path"])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Download failed: {e}")
        raise HTTPException(status_code=502, detail="Download failed")
    filename = f["original_name"].replace('"', "'")
    return Response(
        content=content,
        media_type=f.get("mime") or ctype,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )


@router.delete("/{fid}")
async def delete_file(fid: str, user=Depends(get_current_user)):
    db = get_db()
    try:
        f = await db.files.find_one({"_id": ObjectId(fid)})
    except Exception:
        raise HTTPException(status_code=404, detail="Not found")
    if not f:
        raise HTTPException(status_code=404, detail="Not found")
    if user["role"] != "admin" and f.get("owner_id") != user["id"]:
        raise HTTPException(status_code=403, detail="Forbidden")
    await db.files.update_one({"_id": f["_id"]}, {"$set": {"is_deleted": True}})
    await audit_log("file_deleted", user["id"], user["email"], f["parent_type"], f["parent_id"],
                    {"file_id": fid, "name": f["original_name"]})
    return {"success": True}
