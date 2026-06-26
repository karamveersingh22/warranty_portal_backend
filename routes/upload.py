"""
Upload routes: /api/upload
- POST /dbf
- GET /jobs/{job_id}
- GET /batches
"""

from datetime import datetime
import logging
import os
import tempfile
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status

from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_admin
from models import ImportBatchDocument
from services.dbf_parser import import_dbf_files

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/upload", tags=["upload"])
IMPORT_JOBS: Dict[str, Dict[str, Any]] = {}


def _validate_dbf_upload(file: UploadFile, expected_name: str):
    filename = (file.filename or "").lower()
    if not filename.endswith(".dbf"):
        raise HTTPException(status_code=400, detail=f"{expected_name} must be a .dbf file")


async def _write_upload_to_temp(file: UploadFile, prefix: str) -> str:
    suffix = os.path.splitext(file.filename or ".dbf")[1] or ".dbf"
    handle = tempfile.NamedTemporaryFile(delete=False, prefix=prefix, suffix=suffix)
    try:
        with handle:
            handle.write(await file.read())
        return handle.name
    except Exception:
        try:
            os.remove(handle.name)
        except OSError:
            pass
        raise


def _new_import_job(uploaded_by: str) -> str:
    job_id = uuid4().hex
    now = datetime.utcnow()
    IMPORT_JOBS[job_id] = {
        "job_id": job_id,
        "status": "queued",
        "phase": "queued",
        "message": "Upload received. Import is queued.",
        "uploaded_by": uploaded_by,
        "created_at": now,
        "updated_at": now,
        "booksale_rows": 0,
        "serials_rows": 0,
        "processed_rows": 0,
        "total_rows": 0,
        "inserted_count": 0,
        "updated_count": 0,
        "ignored_count": 0,
        "failed_count": 0,
        "progress_percent": 0,
        "batch_id": None,
        "result": None,
        "error": None,
    }
    return job_id


def _update_import_job(job_id: str, **updates):
    job = IMPORT_JOBS.get(job_id)
    if not job:
        return

    total_rows = updates.get("total_rows", job.get("total_rows", 0)) or 0
    processed_rows = updates.get("processed_rows", job.get("processed_rows", 0)) or 0
    if total_rows:
        updates["progress_percent"] = min(round((processed_rows / total_rows) * 100, 1), 100)

    job.update(updates)
    job["updated_at"] = datetime.utcnow()


async def _run_dbf_import_job(
    job_id: str,
    db,
    booksale_path: str,
    serials_path: str,
    uploaded_by: str,
):
    temp_files = [booksale_path, serials_path]

    async def progress_callback(payload: Dict[str, Any]):
        message_by_phase = {
            "parsing_booksale": "Reading BOOKSALE.dbf",
            "parsing_serials": "Reading SERIALS.dbf",
            "joining_records": "Matching SERIALS pieces with BOOKSALE bills by MAIN_KEY",
            "database_import": "Writing product pieces into MongoDB",
            "completed": "DBF import completed",
        }
        phase = payload.get("phase", "processing")
        job_updates = dict(payload)
        job_updates.pop("message", None)
        _update_import_job(
            job_id,
            status="running",
            message=payload.get("message") or message_by_phase.get(phase, "Processing DBF import"),
            **job_updates,
        )

    try:
        _update_import_job(
            job_id,
            status="running",
            phase="starting",
            message="Starting DBF import",
        )

        report = await import_dbf_files(db, booksale_path, serials_path, progress_callback)
        now = datetime.utcnow()
        failed_rows = report.failed_rows

        batch_record = ImportBatchDocument(**{
            "uploaded_by": uploaded_by,
            "uploaded_at": now,
            "booksale_rows": report.booksale_rows,
            "serials_rows": report.serials_rows,
            "pieces_inserted": report.inserted_count,
            "pieces_updated": report.updated_count,
            "pieces_failed": report.failed_count,
            "failed_rows": failed_rows,
            "source": "dbf_upload",
        }).to_mongo()

        result = await db[COLLECTIONS["import_batches"]].insert_one(batch_record)
        response_payload = {
            "message": "DBF import completed",
            "batch_id": str(result.inserted_id),
            "inserted_count": report.inserted_count,
            "updated_count": report.updated_count,
            "ignored_count": report.ignored_count,
            "failed_count": report.failed_count,
            "failed_rows": failed_rows,
            "report": report.to_response(),
        }

        _update_import_job(
            job_id,
            status="completed",
            phase="completed",
            message="DBF import completed",
            progress_percent=100,
            batch_id=str(result.inserted_id),
            result=response_payload,
            booksale_rows=report.booksale_rows,
            serials_rows=report.serials_rows,
            processed_rows=report.joined_rows,
            total_rows=report.joined_rows,
            inserted_count=report.inserted_count,
            updated_count=report.updated_count,
            ignored_count=report.ignored_count,
            failed_count=report.failed_count,
        )

    except Exception as exc:
        logger.exception("Error in DBF import job %s: %s", job_id, exc)
        _update_import_job(
            job_id,
            status="failed",
            phase="failed",
            message="DBF import failed",
            error=str(exc),
        )
    finally:
        for temp_file in temp_files:
            try:
                if os.path.exists(temp_file):
                    os.remove(temp_file)
            except OSError as exc:
                logger.warning("Failed to clean up temp file %s: %s", temp_file, exc)


@router.post("/dbf")
async def upload_dbf_files(
    background_tasks: BackgroundTasks,
    booksale_file: UploadFile = File(...),
    serials_file: UploadFile = File(...),
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Upload BOOKSALE.dbf and SERIALS.dbf, then start a tracked import job."""
    try:
        _validate_dbf_upload(booksale_file, "booksale_file")
        _validate_dbf_upload(serials_file, "serials_file")

        booksale_path = await _write_upload_to_temp(booksale_file, "booksale_")
        serials_path = await _write_upload_to_temp(serials_file, "serials_")

        uploaded_by = current_user.get("email", "")
        job_id = _new_import_job(uploaded_by)
        background_tasks.add_task(
            _run_dbf_import_job,
            job_id,
            db,
            booksale_path,
            serials_path,
            uploaded_by,
        )

        return {
            "message": "DBF upload received. Import started.",
            "job_id": job_id,
            "status": "queued",
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in upload_dbf_files: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Failed to process DBF files: {str(e)}")


@router.get("/jobs/{job_id}")
async def get_import_job(
    job_id: str,
    current_user: dict = Depends(get_current_admin),
):
    """Return live DBF import progress for an upload job."""
    job = IMPORT_JOBS.get(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import job not found. Restart the import if the backend was restarted.",
        )
    return job


@router.delete("/reset-data")
async def reset_product_data(
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Delete all product pieces, registered products, enquiries, warranty rules, and import batches for a clean re-import."""
    try:
        results = {}
        for col_name in ["product_pieces", "registered_products", "enquiries", "warranty_rules", "import_batches"]:
            result = await db[COLLECTIONS[col_name]].delete_many({})
            results[col_name] = result.deleted_count

        return {
            "message": "All product data has been reset",
            "deleted": results,
        }
    except Exception as e:
        logger.exception("Error in reset_product_data: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to reset data")


@router.get("/batches")
async def get_import_batches(
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
    limit: int = 10,
):
    """Get DBF import history for admins."""
    try:
        batches_collection = db[COLLECTIONS["import_batches"]]
        batches = await batches_collection.find().sort("uploaded_at", -1).limit(limit).to_list(None)

        return {
            "batches": [
                {
                    "id": str(batch["_id"]),
                    "uploaded_by": batch.get("uploaded_by"),
                    "uploaded_at": batch.get("uploaded_at"),
                    "booksale_rows": batch.get("booksale_rows", 0),
                    "serials_rows": batch.get("serials_rows", 0),
                    "pieces_inserted": batch.get("pieces_inserted", 0),
                    "pieces_updated": batch.get("pieces_updated", 0),
                    "pieces_failed": batch.get("pieces_failed", 0),
                    "failed_rows": batch.get("failed_rows", []),
                    "source": batch.get("source"),
                }
                for batch in batches
            ],
            "total": len(batches),
        }

    except Exception as e:
        logger.exception("Error in get_import_batches: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch import history")
