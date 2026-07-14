"""Public catalogue viewing and admin-managed PDF replacement."""

from datetime import datetime
from urllib.parse import quote

from bson import ObjectId
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from database import get_database
from middleware.auth_guard import get_current_admin

router = APIRouter(prefix="/api/catalogue", tags=["catalogue"])

SETTINGS_COLLECTION = "catalogue_settings"
SETTINGS_ID = "current"
GRIDFS_BUCKET = "catalogue_files"
MAX_CATALOGUE_BYTES = 25 * 1024 * 1024


def _public_metadata(document: dict | None) -> dict:
    if not document or not document.get("file_id"):
        return {"available": False}
    return {
        "available": True,
        "filename": document.get("filename", "Safrina Mattress Catalogue.pdf"),
        "size": document.get("size", 0),
        "uploaded_at": document.get("uploaded_at"),
    }


@router.get("/status")
async def get_catalogue_status(db=Depends(get_database)):
    """Return public metadata for the currently active catalogue."""
    document = await db[SETTINGS_COLLECTION].find_one({"_id": SETTINGS_ID})
    return _public_metadata(document)


@router.get("/file")
async def get_catalogue_file(
    download: bool = Query(False),
    db=Depends(get_database),
):
    """Stream the current catalogue publicly for embedding or download."""
    document = await db[SETTINGS_COLLECTION].find_one({"_id": SETTINGS_ID})
    if not document or not document.get("file_id"):
        raise HTTPException(status_code=404, detail="Catalogue is not available yet")

    bucket = AsyncIOMotorGridFSBucket(db, bucket_name=GRIDFS_BUCKET)
    try:
        stream = await bucket.open_download_stream(ObjectId(document["file_id"]))
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Catalogue file is unavailable") from exc

    async def content():
        while True:
            chunk = await stream.read(1024 * 1024)
            if not chunk:
                break
            yield chunk

    filename = document.get("filename", "Safrina Mattress Catalogue.pdf")
    disposition = "attachment" if download else "inline"
    encoded_filename = quote(filename)
    return StreamingResponse(
        content(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(document.get("size", 0)),
            "Cache-Control": "no-store",
        },
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def upload_catalogue(
    catalogue_file: UploadFile = File(...),
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Replace the active catalogue PDF and remove the previous file."""
    filename = (catalogue_file.filename or "").strip()
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are allowed")
    if catalogue_file.content_type not in {"application/pdf", "application/octet-stream"}:
        raise HTTPException(status_code=400, detail="The uploaded file must be a PDF")

    data = await catalogue_file.read(MAX_CATALOGUE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=400, detail="The PDF file is empty")
    if len(data) > MAX_CATALOGUE_BYTES:
        raise HTTPException(status_code=413, detail="The catalogue PDF must be 25 MB or smaller")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="The uploaded file is not a valid PDF")

    bucket = AsyncIOMotorGridFSBucket(db, bucket_name=GRIDFS_BUCKET)
    new_file_id = await bucket.upload_from_stream(
        filename,
        data,
        metadata={"content_type": "application/pdf"},
    )
    now = datetime.utcnow()
    previous = None
    try:
        previous = await db[SETTINGS_COLLECTION].find_one_and_update(
            {"_id": SETTINGS_ID},
            {
                "$set": {
                    "file_id": new_file_id,
                    "filename": filename,
                    "size": len(data),
                    "uploaded_at": now,
                    "uploaded_by": current_user.get("email", ""),
                }
            },
            upsert=True,
        )
    except Exception:
        await bucket.delete(new_file_id)
        raise

    old_file_id = previous.get("file_id") if previous else None
    if old_file_id and old_file_id != new_file_id:
        try:
            await bucket.delete(ObjectId(old_file_id))
        except Exception:
            # The new catalogue is already active. A missing/stale old file must
            # not make an otherwise successful replacement fail.
            pass

    return {
        "message": "Catalogue updated successfully",
        **_public_metadata({
            "file_id": new_file_id,
            "filename": filename,
            "size": len(data),
            "uploaded_at": now,
        }),
    }
