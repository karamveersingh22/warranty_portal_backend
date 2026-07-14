"""
Product piece routes.

Exposes exact product piece endpoints and keeps the existing /api/pieces aliases.
"""

from datetime import datetime
import logging
import re
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from bson import ObjectId

from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_admin, get_current_user
from services.warranty_calculator import calculate_warranty

logger = logging.getLogger(__name__)
router = APIRouter(tags=["pieces"])


def _clean_piece(piece: str) -> str:
    return piece.strip()


def _object_id_to_str(value: Any) -> Optional[str]:
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _address_line(*parts: Optional[str]) -> str:
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def _product_info(product: dict, include_company_traceability: bool = True) -> Dict[str, Any]:
    info = {
        "piece": product.get("piece"),
        "i_code": product.get("i_code"),
        "item_name": product.get("item_name"),
        "product_type": product.get("product_type", ""),
        "category": product.get("category", ""),
        "size": product.get("size", ""),
        "describe": product.get("describe"),
        "created_at": product.get("created_at"),
        "updated_at": product.get("updated_at"),
    }
    if include_company_traceability:
        info.update({
            "bill": product.get("bill"),
            "bill_date": product.get("bill_date"),
            "main_key": product.get("main_key"),
            "has_booksale_match": product.get("has_booksale_match", False),
        })
    return info


def _distributor_info(product: dict) -> Dict[str, Any]:
    return {
        "code": product.get("distributor_code"),
        "name": product.get("distributor_name"),
        "address1": product.get("distributor_add1"),
        "address2": product.get("distributor_add2"),
        "address": _address_line(product.get("distributor_add1"), product.get("distributor_add2")),
        "city": product.get("distributor_city"),
    }


def _dealer_info(product: dict) -> Dict[str, Any]:
    return {
        "code": product.get("dealer_code"),
        "name": product.get("dealer_name"),
        "address1": product.get("dealer_add1"),
        "address2": product.get("dealer_add2"),
        "address": _address_line(product.get("dealer_add1"), product.get("dealer_add2")),
        "city": product.get("dealer_city"),
        "state": product.get("dealer_state"),
        "phone": product.get("dealer_phone"),
    }


def _customer_info(customer: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not customer:
        return None
    return {
        "id": str(customer.get("_id")),
        "name": customer.get("name"),
        "email": customer.get("email"),
        "phone": customer.get("phone"),
        "address": customer.get("address"),
        "city": customer.get("city"),
        "state": customer.get("state"),
        "profile_complete": customer.get("profile_complete", False),
        "created_at": customer.get("created_at"),
    }


def _warranty_info(registration: Optional[dict]) -> Optional[Dict[str, Any]]:
    if not registration:
        return None

    warranty_start = registration.get("warranty_start")
    warranty_end = registration.get("warranty_end")
    if not warranty_start or not warranty_end:
        return None

    live_warranty = calculate_warranty(
        warranty_start,
        warranty_end,
    )
    return {
        "id": str(registration.get("_id")),
        "customer_id": _object_id_to_str(registration.get("customer_id")),
        "customer_email": registration.get("customer_email"),
        "piece": registration.get("piece"),
        "item_name": registration.get("item_name"),
        "i_code": registration.get("i_code"),
        "category": registration.get("category"),
        "dealer_bill_number": registration.get("dealer_bill_number"),
        "dealer_bill_date": registration.get("dealer_bill_date"),
        "warranty_rule_id": _object_id_to_str(registration.get("warranty_rule_id")),
        "warranty_start": registration.get("warranty_start"),
        "warranty_end": registration.get("warranty_end"),
        "warranty_months": registration.get("warranty_months"),
        "registered_at": registration.get("registered_at"),
        "stored_status": registration.get("status"),
        "status": live_warranty.get("status"),
        "remaining_days": live_warranty.get("remaining_days"),
        "remaining_months": live_warranty.get("remaining_months"),
        "percent_elapsed": live_warranty.get("percent_elapsed"),
    }


def _enquiry_info(enquiry: dict) -> Dict[str, Any]:
    return {
        "id": str(enquiry.get("_id")),
        "customer_id": _object_id_to_str(enquiry.get("customer_id")),
        "customer_email": enquiry.get("customer_email"),
        "piece": enquiry.get("piece"),
        "item_name": enquiry.get("item_name"),
        "issue_type": enquiry.get("issue_type"),
        "description": enquiry.get("description"),
        "status": enquiry.get("status"),
        "admin_note": enquiry.get("admin_note"),
        "created_at": enquiry.get("created_at"),
        "updated_at": enquiry.get("updated_at"),
    }


async def _find_product_or_404(db, piece: str) -> dict:
    product = await db[COLLECTIONS["product_pieces"]].find_one({"piece": _clean_piece(piece)})
    if not product:
        raise HTTPException(status_code=404, detail="Piece not found")
    return product


def _regex(value: str) -> Dict[str, Any]:
    return {"$regex": re.escape(value.strip()), "$options": "i"}


def _code_filter(field: str, value: str) -> Dict[str, Any]:
    options = [{field: _regex(value)}]
    try:
        options.append({field: int(value)})
    except ValueError:
        pass
    return {"$or": options}


async def _build_search_query(
    db,
    q: Optional[str],
    piece: Optional[str],
    i_code: Optional[str],
    item_name: Optional[str],
    bill: Optional[str],
    main_key: Optional[str],
    dealer_code: Optional[str],
    dealer_name: Optional[str],
    distributor_code: Optional[str],
    distributor_name: Optional[str],
    city: Optional[str],
    has_booksale_match: Optional[bool],
    registered: Optional[bool],
    bill_date_from: Optional[datetime],
    bill_date_to: Optional[datetime],
) -> Dict[str, Any]:
    filters = []

    if q:
        filters.append({
            "$or": [
                {"piece": _regex(q)},
                {"item_name": _regex(q)},
                {"i_code": _regex(q)},
                {"bill": _regex(q)},
                {"dealer_name": _regex(q)},
                {"distributor_name": _regex(q)},
            ]
        })
    if piece:
        filters.append({"piece": _regex(piece)})
    if i_code:
        filters.append({"i_code": _regex(i_code)})
    if item_name:
        filters.append({"item_name": _regex(item_name)})
    if bill:
        filters.append({"bill": _regex(bill)})
    if main_key:
        filters.append({"main_key": _regex(main_key)})
    if dealer_code:
        filters.append(_code_filter("dealer_code", dealer_code))
    if dealer_name:
        filters.append({"dealer_name": _regex(dealer_name)})
    if distributor_code:
        filters.append(_code_filter("distributor_code", distributor_code))
    if distributor_name:
        filters.append({"distributor_name": _regex(distributor_name)})
    if city:
        filters.append({
            "$or": [
                {"dealer_city": _regex(city)},
                {"distributor_city": _regex(city)},
            ]
        })
    if has_booksale_match is not None:
        filters.append({"has_booksale_match": has_booksale_match})
    if bill_date_from or bill_date_to:
        date_filter = {}
        if bill_date_from:
            date_filter["$gte"] = bill_date_from
        if bill_date_to:
            date_filter["$lte"] = bill_date_to
        filters.append({"bill_date": date_filter})
    if registered is not None:
        registered_pieces = await db[COLLECTIONS["registered_products"]].distinct("piece")
        filters.append({"piece": {"$in" if registered else "$nin": registered_pieces}})

    if not filters:
        return {}
    if len(filters) == 1:
        return filters[0]
    return {"$and": filters}


async def _lookup_piece(piece: str, current_user: dict, db) -> Dict[str, Any]:
    clean_piece = _clean_piece(piece)
    product = await _find_product_or_404(db, clean_piece)
    registration = await db[COLLECTIONS["registered_products"]].find_one({"piece": clean_piece})

    response = {
        "piece": clean_piece,
        "is_registered": registration is not None,
        "registered_by": registration.get("customer_email") if registration and current_user.get("role") == "admin" else None,
        "product_information": _product_info(product, include_company_traceability=current_user.get("role") == "admin"),
        "dealer_information": _dealer_info(product),
    }
    if current_user.get("role") == "admin":
        response["distributor_information"] = _distributor_info(product)
    return response


async def _trace_piece(piece: str, current_user: dict, db) -> Dict[str, Any]:
    clean_piece = _clean_piece(piece)
    product = await _find_product_or_404(db, clean_piece)
    registration = await db[COLLECTIONS["registered_products"]].find_one({"piece": clean_piece})

    customer = None
    if registration:
        customer = await db[COLLECTIONS["customers"]].find_one(
            {"_id": registration.get("customer_id")}
        )

    enquiries = await db[COLLECTIONS["enquiries"]].find({"piece": clean_piece}).sort(
        "created_at", -1
    ).to_list(None)

    return {
        "piece": clean_piece,
        "product": _product_info(product),
        "distributor": _distributor_info(product),
        "dealer": _dealer_info(product),
        "customer": _customer_info(customer),
        "warranty": _warranty_info(registration),
        "enquiries_count": len(enquiries),
        "enquiries": [_enquiry_info(enquiry) for enquiry in enquiries],
    }


async def _search_pieces(
    db,
    q: Optional[str],
    piece: Optional[str],
    i_code: Optional[str],
    item_name: Optional[str],
    bill: Optional[str],
    main_key: Optional[str],
    dealer_code: Optional[str],
    dealer_name: Optional[str],
    distributor_code: Optional[str],
    distributor_name: Optional[str],
    city: Optional[str],
    has_booksale_match: Optional[bool],
    registered: Optional[bool],
    bill_date_from: Optional[datetime],
    bill_date_to: Optional[datetime],
    skip: int,
    limit: int,
    sort_by: str,
    sort_dir: str,
) -> Dict[str, Any]:
    collection = db[COLLECTIONS["product_pieces"]]
    query = await _build_search_query(
        db,
        q,
        piece,
        i_code,
        item_name,
        bill,
        main_key,
        dealer_code,
        dealer_name,
        distributor_code,
        distributor_name,
        city,
        has_booksale_match,
        registered,
        bill_date_from,
        bill_date_to,
    )
    allowed_sort_fields = {
        "piece",
        "item_name",
        "i_code",
        "bill",
        "bill_date",
        "dealer_name",
        "distributor_name",
        "created_at",
        "updated_at",
    }
    sort_field = sort_by if sort_by in allowed_sort_fields else "piece"
    sort_direction = -1 if sort_dir.lower() == "desc" else 1

    total = await collection.count_documents(query)
    products = await collection.find(query).sort(sort_field, sort_direction).skip(skip).limit(
        limit
    ).to_list(None)
    registered_piece_set = set(
        await db[COLLECTIONS["registered_products"]].distinct(
            "piece", {"piece": {"$in": [product.get("piece") for product in products]}}
        )
    )

    return {
        "query": q,
        "filters": {
            "piece": piece,
            "i_code": i_code,
            "item_name": item_name,
            "bill": bill,
            "main_key": main_key,
            "dealer_code": dealer_code,
            "dealer_name": dealer_name,
            "distributor_code": distributor_code,
            "distributor_name": distributor_name,
            "city": city,
            "has_booksale_match": has_booksale_match,
            "registered": registered,
            "bill_date_from": bill_date_from,
            "bill_date_to": bill_date_to,
        },
        "total": total,
        "count": len(products),
        "skip": skip,
        "limit": limit,
        "sort_by": sort_field,
        "sort_dir": "desc" if sort_direction == -1 else "asc",
        "results": [
            {
                "piece": product.get("piece"),
                "is_registered": product.get("piece") in registered_piece_set,
                "product_information": _product_info(product),
                "distributor_information": _distributor_info(product),
                "dealer_information": _dealer_info(product),
            }
            for product in products
        ],
    }


@router.get("/pieces/lookup/{piece}")
@router.get("/api/pieces/lookup/{piece}", include_in_schema=False)
async def lookup_piece(
    piece: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """Return product, distributor, and dealer information for a piece."""
    try:
        return await _lookup_piece(piece, current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in lookup_piece: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to lookup piece")


@router.get("/pieces/trace/{piece}")
@router.get("/api/pieces/trace/{piece}", include_in_schema=False)
async def trace_piece(
    piece: str,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Return full piece traceability. Admin only."""
    try:
        return await _trace_piece(piece, current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in trace_piece: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to trace piece")


@router.get("/pieces/search")
@router.get("/api/pieces/search", include_in_schema=False)
async def search_pieces(
    q: Optional[str] = Query(None, min_length=1),
    piece: Optional[str] = Query(None, min_length=1),
    i_code: Optional[str] = Query(None, min_length=1),
    item_name: Optional[str] = Query(None, min_length=1),
    bill: Optional[str] = Query(None, min_length=1),
    main_key: Optional[str] = Query(None, min_length=1),
    dealer_code: Optional[str] = Query(None, min_length=1),
    dealer_name: Optional[str] = Query(None, min_length=1),
    distributor_code: Optional[str] = Query(None, min_length=1),
    distributor_name: Optional[str] = Query(None, min_length=1),
    city: Optional[str] = Query(None, min_length=1),
    has_booksale_match: Optional[bool] = Query(None),
    registered: Optional[bool] = Query(None),
    bill_date_from: Optional[datetime] = Query(None),
    bill_date_to: Optional[datetime] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=200),
    sort_by: str = Query("piece"),
    sort_dir: str = Query("asc", pattern="^(asc|desc)$"),
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Search and filter product pieces. Admin only."""
    try:
        return await _search_pieces(
            db,
            q,
            piece,
            i_code,
            item_name,
            bill,
            main_key,
            dealer_code,
            dealer_name,
            distributor_code,
            distributor_name,
            city,
            has_booksale_match,
            registered,
            bill_date_from,
            bill_date_to,
            skip,
            limit,
            sort_by,
            sort_dir,
        )
    except Exception as e:
        logger.exception("Error in search_pieces: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to search pieces")
