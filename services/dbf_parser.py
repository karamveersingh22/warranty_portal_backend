"""
DBF import engine for product piece master data.

Parses BOOKSALE.dbf and SERIALS.dbf, joins records by main_key, and upserts
product pieces by the unique piece number.
"""

from dataclasses import dataclass, field
from datetime import date, datetime, time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
import inspect
import logging

from dbfread import DBF
from pymongo.errors import DuplicateKeyError
from pydantic import ValidationError

from models import ProductPieceDocument

logger = logging.getLogger(__name__)


import re as _re

_SIZE_PATTERN = _re.compile(r'\d+[Xx]\d+(?:[Xx]\d+)?$')


def parse_item_name(raw: str) -> tuple[str, str, str]:
    """Split an item_name like 'MATTRESS LEO 35X72X5' into (product_type, category, size)."""
    parts = raw.strip().split()
    if not parts:
        return ("", "", "")
    product_type = parts[0] if parts else ""
    size = ""
    if len(parts) >= 2 and _SIZE_PATTERN.search(parts[-1]):
        size = parts[-1]
        middle = parts[1:-1]
    else:
        middle = parts[1:]
    category = " ".join(middle) if middle else ""
    return (product_type, category, size)

ProgressCallback = Callable[[Dict[str, Any]], Optional[Awaitable[None]]]


@dataclass
class ImportReport:
    booksale_rows: int = 0
    serials_rows: int = 0
    joined_rows: int = 0
    inserted_count: int = 0
    updated_count: int = 0
    ignored_count: int = 0
    failed_rows: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def failed_count(self) -> int:
        return len(self.failed_rows)

    def to_response(self) -> Dict[str, Any]:
        return {
            "booksale_rows": self.booksale_rows,
            "serials_rows": self.serials_rows,
            "joined_rows": self.joined_rows,
            "inserted_count": self.inserted_count,
            "updated_count": self.updated_count,
            "ignored_count": self.ignored_count,
            "failed_count": self.failed_count,
            "failed_rows": self.failed_rows,
        }


def _safe_failed_record(record: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in record.items()
    }


def _read_field(record: dict, field: str, default=None):
    """Read DBF fields case-insensitively and trim string values."""
    field_lower = field.lower()
    for key, value in record.items():
        if str(key).lower() == field_lower:
            if isinstance(value, str):
                return value.strip()
            return value
    return default


def _read_text_field(record: dict, field: str, default: str = "") -> str:
    """Read a DBF value that must be stored as text, preserving leading zeroes."""
    value = _read_field(record, field, default)
    if value in (None, ""):
        return default
    return str(value).strip()


def _dbf_date_to_datetime(value):
    """Convert DBF date values into MongoDB-compatible datetimes."""
    if value in ("", None):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min)
    return value


async def _send_progress(
    progress_callback: Optional[ProgressCallback],
    payload: Dict[str, Any],
):
    if not progress_callback:
        return
    result = progress_callback(payload)
    if inspect.isawaitable(result):
        await result


def parse_booksale_dbf(file_path: str) -> Tuple[Dict[str, dict], List[Dict[str, Any]], int]:
    """Parse BOOKSALE.dbf records keyed by MAIN_KEY."""
    booksale_by_main_key: Dict[str, dict] = {}
    failed_rows: List[Dict[str, Any]] = []
    row_count = 0

    for row_number, record in enumerate(DBF(file_path, ignore_missing_memofile=True), start=1):
        row_count = row_number
        try:
            main_key = _read_text_field(record, "main_key")
            if not main_key:
                failed_rows.append({
                    "source": "booksale",
                    "row_number": row_number,
                    "reason": "Missing main_key",
                    "record": _safe_failed_record(dict(record)),
                })
                continue

            booksale_by_main_key[main_key] = {
                "distributor_code": _read_field(record, "code"),
                "distributor_name": _read_text_field(record, "account_n"),
                "bill": _read_text_field(record, "bill"),
                "bill_date": _dbf_date_to_datetime(_read_field(record, "date")),
                "distributor_add1": _read_text_field(record, "add_1"),
                "distributor_add2": _read_text_field(record, "add_2"),
                "distributor_city": _read_text_field(record, "city"),
                "dealer_code": _read_field(record, "del_code"),
                "dealer_name": _read_text_field(record, "del_name"),
                "dealer_add1": _read_text_field(record, "del_add1"),
                "dealer_add2": _read_text_field(record, "del_add2"),
                "dealer_city": _read_text_field(record, "del_city"),
                "dealer_state": _read_text_field(record, "del_state"),
                "dealer_phone": _read_text_field(record, "del_phone"),
            }
        except Exception as exc:
            failed_rows.append({
                "source": "booksale",
                "row_number": row_number,
                "reason": str(exc),
                "record": _safe_failed_record(dict(record)),
            })

    logger.info("Parsed BOOKSALE.dbf: %s records", len(booksale_by_main_key))
    return booksale_by_main_key, failed_rows, row_count


def parse_serials_dbf(file_path: str) -> Tuple[List[dict], List[Dict[str, Any]]]:
    """Parse SERIALS.dbf records."""
    serials: List[dict] = []
    failed_rows: List[Dict[str, Any]] = []

    for row_number, record in enumerate(DBF(file_path, ignore_missing_memofile=True), start=1):
        try:
            raw_item_name = _read_text_field(record, "item_name")
            product_type, category, size = parse_item_name(raw_item_name)
            serials.append({
                "row_number": row_number,
                "i_code": _read_text_field(record, "i_code"),
                "item_name": raw_item_name,
                "product_type": product_type,
                "category": category,
                "size": size,
                "piece": _read_text_field(record, "piece"),
                "bill_date": _dbf_date_to_datetime(_read_field(record, "date")),
                "bill": _read_text_field(record, "bill"),
                "main_key": _read_text_field(record, "main_key"),
                "describe": _read_text_field(record, "describe"),
            })
        except Exception as exc:
            failed_rows.append({
                "source": "serials",
                "row_number": row_number,
                "reason": str(exc),
                "record": _safe_failed_record(dict(record)),
            })

    logger.info("Parsed SERIALS.dbf: %s records", len(serials))
    return serials, failed_rows


def join_records(
    serials: List[dict],
    booksale_by_main_key: Dict[str, dict],
) -> Tuple[List[dict], List[Dict[str, Any]]]:
    """Join SERIALS and BOOKSALE rows using main_key."""
    now = datetime.utcnow()
    joined_records: List[dict] = []
    failed_rows: List[Dict[str, Any]] = []

    for serial_record in serials:
        row_number = serial_record.get("row_number")
        main_key = serial_record.get("main_key", "")
        booksale_record = booksale_by_main_key.get(main_key, {})
        bill_date = booksale_record.get("bill_date") or serial_record.get("bill_date")

        product_record = {
            "piece": serial_record.get("piece", ""),
            "i_code": serial_record.get("i_code", ""),
            "item_name": serial_record.get("item_name", ""),
            "product_type": serial_record.get("product_type", ""),
            "category": serial_record.get("category", ""),
            "size": serial_record.get("size", ""),
            "describe": serial_record.get("describe", ""),
            "bill": booksale_record.get("bill") or serial_record.get("bill") or "",
            "bill_date": bill_date,
            "main_key": main_key,
            "has_booksale_match": bool(booksale_record),
            "distributor_code": booksale_record.get("distributor_code"),
            "distributor_name": booksale_record.get("distributor_name", ""),
            "distributor_add1": booksale_record.get("distributor_add1", ""),
            "distributor_add2": booksale_record.get("distributor_add2", ""),
            "distributor_city": booksale_record.get("distributor_city", ""),
            "dealer_code": booksale_record.get("dealer_code"),
            "dealer_name": booksale_record.get("dealer_name", ""),
            "dealer_add1": booksale_record.get("dealer_add1", ""),
            "dealer_add2": booksale_record.get("dealer_add2", ""),
            "dealer_city": booksale_record.get("dealer_city", ""),
            "dealer_state": booksale_record.get("dealer_state", ""),
            "dealer_phone": booksale_record.get("dealer_phone", ""),
            "created_at": now,
            "updated_at": now,
        }

        try:
            product = ProductPieceDocument(**product_record)
            joined_records.append(product.to_mongo())
        except ValidationError as exc:
            failed_rows.append({
                "source": "serials",
                "row_number": row_number,
                "piece": product_record.get("piece"),
                "reason": exc.errors()[0]["msg"] if exc.errors() else str(exc),
                "record": _safe_failed_record(product_record),
            })

    logger.info("Joined %s records, %s failed", len(joined_records), len(failed_rows))
    return joined_records, failed_rows


async def upsert_product_pieces(
    db,
    product_records: List[dict],
    progress_callback: Optional[ProgressCallback] = None,
) -> ImportReport:
    """
    Upsert product pieces by piece.

    Rules:
    - Insert when the piece does not exist.
    - Update only when incoming bill_date is newer than the stored bill_date.
    - Ignore existing pieces with same or older incoming bill_date.
    """
    report = ImportReport(joined_rows=len(product_records))
    collection = db["product_pieces"]

    def has_better_traceability(existing: dict, incoming: dict) -> bool:
        if incoming.get("has_booksale_match") and not existing.get("has_booksale_match"):
            return True

        trace_fields = [
            "distributor_code",
            "distributor_name",
            "distributor_add1",
            "distributor_add2",
            "distributor_city",
            "dealer_code",
            "dealer_name",
            "dealer_add1",
            "dealer_add2",
            "dealer_city",
            "dealer_state",
            "dealer_phone",
        ]
        return any(incoming.get(field) and not existing.get(field) for field in trace_fields)

    total_records = len(product_records)
    await _send_progress(progress_callback, {
        "phase": "database_import",
        "processed_rows": 0,
        "total_rows": total_records,
        "inserted_count": 0,
        "updated_count": 0,
        "ignored_count": 0,
        "failed_count": 0,
    })

    for index, record in enumerate(product_records, start=1):
        piece = record.get("piece")
        try:
            existing = await collection.find_one({"piece": piece})
            if not existing:
                await collection.insert_one(record)
                report.inserted_count += 1
            else:
                incoming_bill_date = record.get("bill_date")
                existing_bill_date = existing.get("bill_date")
                is_newer = incoming_bill_date and (
                    not existing_bill_date or incoming_bill_date > existing_bill_date
                )
                if is_newer or has_better_traceability(existing, record):
                    record.pop("_id", None)
                    record["updated_at"] = datetime.utcnow()
                    await collection.update_one({"piece": piece}, {"$set": record})
                    report.updated_count += 1
                else:
                    report.ignored_count += 1

        except DuplicateKeyError as exc:
            report.failed_rows.append({
                "source": "upsert",
                "piece": piece,
                "reason": f"Duplicate piece conflict: {exc.details or str(exc)}",
                "record": _safe_failed_record(record),
            })
        except Exception as exc:
            report.failed_rows.append({
                "source": "upsert",
                "piece": piece,
                "reason": str(exc),
                "record": _safe_failed_record(record),
            })
            logger.exception("Failed to upsert piece %s: %s", piece, exc)

        if index % 250 == 0 or index == total_records:
            await _send_progress(progress_callback, {
                "phase": "database_import",
                "processed_rows": index,
                "total_rows": total_records,
                "inserted_count": report.inserted_count,
                "updated_count": report.updated_count,
                "ignored_count": report.ignored_count,
                "failed_count": report.failed_count,
            })

    logger.info(
        "DBF upsert complete: %s inserted, %s updated, %s ignored, %s failed",
        report.inserted_count,
        report.updated_count,
        report.ignored_count,
        report.failed_count,
    )
    return report


async def import_dbf_files(
    db,
    booksale_path: str,
    serials_path: str,
    progress_callback: Optional[ProgressCallback] = None,
) -> ImportReport:
    """Run the full DBF import pipeline and return an import report."""
    await _send_progress(progress_callback, {
        "phase": "parsing_booksale",
        "processed_rows": 0,
        "total_rows": 0,
        "message": "Reading BOOKSALE.dbf",
    })
    booksale_by_main_key, booksale_failed, booksale_rows = parse_booksale_dbf(booksale_path)
    await _send_progress(progress_callback, {
        "phase": "parsing_serials",
        "booksale_rows": booksale_rows,
        "processed_rows": 0,
        "total_rows": 0,
        "message": "Reading SERIALS.dbf",
    })
    serials, serials_failed = parse_serials_dbf(serials_path)
    await _send_progress(progress_callback, {
        "phase": "joining_records",
        "booksale_rows": booksale_rows,
        "serials_rows": len(serials),
        "processed_rows": 0,
        "total_rows": len(serials),
        "message": "Joining DBF records by MAIN_KEY",
    })
    product_records, join_failed = join_records(serials, booksale_by_main_key)
    report = await upsert_product_pieces(db, product_records, progress_callback)

    report.booksale_rows = booksale_rows
    report.serials_rows = len(serials)
    report.failed_rows = booksale_failed + serials_failed + join_failed + report.failed_rows
    await _send_progress(progress_callback, {
        "phase": "completed",
        "booksale_rows": report.booksale_rows,
        "serials_rows": report.serials_rows,
        "processed_rows": report.joined_rows,
        "total_rows": report.joined_rows,
        "inserted_count": report.inserted_count,
        "updated_count": report.updated_count,
        "ignored_count": report.ignored_count,
        "failed_count": report.failed_count,
        "message": "DBF import completed",
    })
    return report
