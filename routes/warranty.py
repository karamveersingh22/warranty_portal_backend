"""
Warranty registration routes.

Exposes exact /warranty endpoints and keeps existing /api/warranty aliases.
"""

from datetime import datetime, time
import logging
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo.errors import DuplicateKeyError
from dateutil.relativedelta import relativedelta

from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_admin, get_current_customer
from models import RegisteredProductDocument, RegistrationRequestDocument
from schemas import WarrantyRegisterRequest
from services.customers import (
    PROFILE_REQUIRED_MESSAGE,
    get_customer_by_email,
    has_complete_profile,
    normalize_email,
)
from services.warranty_calculator import calculate_warranty
from services.warranty_eligibility import INELIGIBLE_MESSAGE, is_warranty_eligible

logger = logging.getLogger(__name__)
router = APIRouter(tags=["warranty"])


def _clean_piece(piece: str) -> str:
    return piece.strip()


def _object_id_to_str(value: Any) -> Optional[str]:
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _warranty_progress(registration: dict) -> Dict[str, Any]:
    warranty_start = registration.get("warranty_start")
    warranty_end = registration.get("warranty_end")
    if not warranty_start or not warranty_end:
        raise HTTPException(status_code=500, detail="Registered product warranty window is missing")

    live = calculate_warranty(
        warranty_start,
        warranty_end,
    )
    return {
        "remaining_days": live["remaining_days"],
        "remaining_months": live["remaining_months"],
        "status": live["status"],
        "percentage_used": live["percent_elapsed"],
        "percent_elapsed": live["percent_elapsed"],
    }


def _registration_response(registration: dict, product: Optional[dict] = None) -> Dict[str, Any]:
    progress = _warranty_progress(registration)
    product_info = None
    if product:
        product_info = {
            "piece_id": str(product.get("_id")),
            "piece": product.get("piece"),
            "i_code": product.get("i_code"),
            "item_name": product.get("item_name"),
            "describe": product.get("describe"),
            "dealer_bill_number": registration.get("dealer_bill_number"),
            "dealer_bill_date": registration.get("dealer_bill_date"),
            "dealer_name": product.get("dealer_name"),
            "dealer_city": product.get("dealer_city"),
            "dealer_state": product.get("dealer_state"),
        }

    return {
        "id": str(registration.get("_id")),
        "customer_id": _object_id_to_str(registration.get("customer_id")),
        "piece_id": _object_id_to_str(registration.get("piece_id")),
        "piece": registration.get("piece"),
        "item_name": registration.get("item_name"),
        "i_code": registration.get("i_code"),
        "category": registration.get("category"),
        "warranty_rule_id": _object_id_to_str(registration.get("warranty_rule_id")),
        "warranty_start": registration.get("warranty_start"),
        "warranty_end": registration.get("warranty_end"),
        "warranty_months": registration.get("warranty_months"),
        "dealer_bill_number": registration.get("dealer_bill_number"),
        "dealer_bill_date": registration.get("dealer_bill_date"),
        "registered_at": registration.get("registered_at"),
        "stored_status": registration.get("status"),
        "status": progress["status"],
        "remaining_days": progress["remaining_days"],
        "remaining_months": progress["remaining_months"],
        "percentage_used": progress["percentage_used"],
        "percent_elapsed": progress["percent_elapsed"],
        "product_information": product_info,
    }


async def _get_customer_or_profile_required(db, email: str) -> dict:
    customer = await get_customer_by_email(db, email)
    if not has_complete_profile(customer):
        raise HTTPException(status_code=400, detail=PROFILE_REQUIRED_MESSAGE)
    return customer


async def _get_piece_or_404(db, piece: str) -> dict:
    product = await db[COLLECTIONS["product_pieces"]].find_one({"piece": piece})
    if not product:
        raise HTTPException(status_code=404, detail="Piece not found")
    return product


async def _find_warranty_rule(db, product: dict) -> tuple[dict, str, int]:
    rules_collection = db[COLLECTIONS["warranty_rules"]]
    product_category = (product.get("category") or "").strip()

    if product_category:
        rule = await rules_collection.find_one({
            "category": {"$regex": f"^{product_category}$", "$options": "i"},
            "is_active": True,
        })
        if rule:
            return rule, rule["category"], rule["warranty_months"]

    general_rule = await rules_collection.find_one({
        "category": {"$regex": "^general$", "$options": "i"},
        "is_active": True,
    })
    if general_rule:
        return general_rule, general_rule["category"], general_rule["warranty_months"]

    raise HTTPException(
        status_code=400,
        detail="No active warranty rule matches this product category. Ask an admin to create a warranty rule first.",
    )


async def _register_warranty(request: WarrantyRegisterRequest, current_user: dict, db):
    email = normalize_email(current_user.get("email"))
    piece = _clean_piece(request.piece)
    if not piece:
        raise HTTPException(status_code=400, detail="Piece number is required")
    dealer_bill_date = datetime.combine(request.dealer_bill_date, time.min)

    product = await _get_piece_or_404(db, piece)
    if not is_warranty_eligible(product):
        raise HTTPException(status_code=400, detail=INELIGIBLE_MESSAGE)
    customer = await _get_customer_or_profile_required(db, email)
    existing = await db[COLLECTIONS["registered_products"]].find_one({"piece": piece})
    if existing:
        raise HTTPException(status_code=400, detail="This piece is already registered")

    pending = await db[COLLECTIONS["registration_requests"]].find_one({
        "piece": piece,
        "status": "pending",
    })
    if pending:
        if pending.get("customer_id") == customer["_id"]:
            raise HTTPException(
                status_code=400,
                detail="You already have a pending registration request for this piece awaiting admin approval.",
            )
        raise HTTPException(
            status_code=400,
            detail="A registration request for this piece is already pending review.",
        )

    warranty_rule, category, warranty_months = await _find_warranty_rule(db, product)

    rule_terms = warranty_rule.get("terms", [])
    if rule_terms and not request.terms_accepted:
        raise HTTPException(status_code=400, detail="You must accept the warranty terms before registering")

    request_doc = RegistrationRequestDocument(
        customer_id=customer["_id"],
        customer_email=email,
        piece_id=product["_id"],
        piece=piece,
        item_name=product.get("item_name", ""),
        i_code=product.get("i_code", ""),
        category=category,
        size=product.get("size", ""),
        bill=product.get("bill", ""),
        bill_date=product.get("bill_date"),
        dealer_bill_number=request.dealer_bill_number,
        dealer_bill_date=dealer_bill_date,
        warranty_rule_id=warranty_rule["_id"],
        warranty_months=warranty_months,
        status="pending",
        feedback_required=True,
        feedback_submitted=False,
        requested_at=datetime.utcnow(),
    )
    record = request_doc.to_mongo()
    result = await db[COLLECTIONS["registration_requests"]].insert_one(record)

    return {
        "message": "Your registration request has been submitted and is pending admin approval.",
        "request": {
            "id": str(result.inserted_id),
            "piece": piece,
            "item_name": product.get("item_name", ""),
            "category": category,
            "status": "pending",
            "feedback_required": True,
            "feedback_submitted": False,
        },
    }


def _request_status_message(req: dict) -> str:
    item = req.get("item_name") or "product"
    status = req.get("status")
    if status == "approved":
        return f"Your registration of the {item} has been approved."
    if status == "declined":
        reason = req.get("decline_reason")
        base = "Your registration request has been declined, so either fill the correct details or contact the support team."
        return f"{base} ({reason})" if reason else base
    return "Your registration request is pending admin approval."


async def _get_my_requests(current_user: dict, db):
    email = normalize_email(current_user.get("email"))
    customer = await get_customer_by_email(db, email)
    if not customer:
        return {"requests": [], "total": 0}
    requests = await db[COLLECTIONS["registration_requests"]].find({
        "customer_id": customer["_id"]
    }).sort("requested_at", -1).to_list(None)

    return {
        "requests": [
            {
                "id": str(req.get("_id")),
                "piece": req.get("piece"),
                "item_name": req.get("item_name"),
                "category": req.get("category"),
                "size": req.get("size"),
                "status": req.get("status"),
                "dealer_bill_number": req.get("dealer_bill_number"),
                "dealer_bill_date": req.get("dealer_bill_date"),
                "decline_reason": req.get("decline_reason"),
                "requested_at": req.get("requested_at"),
                "reviewed_at": req.get("reviewed_at"),
                "message": _request_status_message(req),
            }
            for req in requests
        ],
        "total": len(requests),
    }


async def _get_my_products(current_user: dict, db):
    email = normalize_email(current_user.get("email"))
    customer = await get_customer_by_email(db, email)
    if not customer:
        return {"products": [], "total": 0}
    registrations = await db[COLLECTIONS["registered_products"]].find({
        "customer_id": customer["_id"]
    }).sort("registered_at", -1).to_list(None)

    piece_ids = [registration.get("piece_id") for registration in registrations if registration.get("piece_id")]
    products = {}
    if piece_ids:
        product_docs = await db[COLLECTIONS["product_pieces"]].find(
            {"_id": {"$in": piece_ids}}
        ).to_list(None)
        products = {product["_id"]: product for product in product_docs}

    return {
        "products": [
            _registration_response(registration, products.get(registration.get("piece_id")))
            for registration in registrations
        ],
        "total": len(registrations),
    }


async def _get_warranty_product(piece: str, current_user: dict, db):
    email = normalize_email(current_user.get("email"))
    customer = await get_customer_by_email(db, email)
    if not customer:
        raise HTTPException(status_code=404, detail="Product not registered")
    clean_piece = _clean_piece(piece)

    registration = await db[COLLECTIONS["registered_products"]].find_one({
        "customer_id": customer["_id"],
        "piece": clean_piece,
    })
    if not registration:
        raise HTTPException(status_code=404, detail="Product not registered")

    product = await db[COLLECTIONS["product_pieces"]].find_one({
        "_id": registration.get("piece_id")
    }) or await db[COLLECTIONS["product_pieces"]].find_one({"piece": clean_piece})

    enquiries = await db[COLLECTIONS["enquiries"]].find({
        "customer_id": customer["_id"],
        "piece": clean_piece,
    }).sort("created_at", -1).to_list(None)

    response = _registration_response(registration, product)
    response["enquiries"] = [
        {
            "id": str(enquiry.get("_id")),
            "issue_type": enquiry.get("issue_type"),
            "description": enquiry.get("description"),
            "status": enquiry.get("status"),
            "admin_note": enquiry.get("admin_note"),
            "created_at": enquiry.get("created_at"),
            "updated_at": enquiry.get("updated_at"),
        }
        for enquiry in enquiries
    ]
    return response


@router.get("/warranty/terms/{piece}")
@router.get("/api/warranty/terms/{piece}", include_in_schema=False)
async def get_warranty_terms(
    piece: str,
    current_user: dict = Depends(get_current_customer),
    db=Depends(get_database),
):
    """Return the warranty terms for a piece's category so the customer can review before registering."""
    try:
        clean = _clean_piece(piece)
        product = await _get_piece_or_404(db, clean)
        if not is_warranty_eligible(product):
            raise HTTPException(status_code=400, detail=INELIGIBLE_MESSAGE)
        rule, category, warranty_months = await _find_warranty_rule(db, product)
        return {
            "piece": clean,
            "category": category,
            "warranty_months": warranty_months,
            "terms": rule.get("terms", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in get_warranty_terms: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch warranty terms")


@router.post("/warranty/register")
@router.post("/api/warranty/register", include_in_schema=False)
async def register_warranty(
    request: WarrantyRegisterRequest,
    current_user: dict = Depends(get_current_customer),
    db=Depends(get_database),
):
    """Register a warranty for an existing, unregistered piece."""
    try:
        return await _register_warranty(request, current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in register_warranty: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to register warranty")


@router.get("/warranty/my-requests")
@router.get("/api/warranty/my-requests", include_in_schema=False)
async def get_my_requests(
    current_user: dict = Depends(get_current_customer),
    db=Depends(get_database),
):
    """Return the current customer's registration requests with status messages."""
    try:
        return await _get_my_requests(current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in get_my_requests: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch registration requests")


@router.get("/warranty/my-products")
@router.get("/api/warranty/my-products", include_in_schema=False)
async def get_my_products(
    current_user: dict = Depends(get_current_customer),
    db=Depends(get_database),
):
    """Return all warranties registered by the current customer."""
    try:
        return await _get_my_products(current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in get_my_products: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch products")


@router.get("/warranty/product/{piece}")
@router.get("/api/warranty/product/{piece}", include_in_schema=False)
async def get_product_detail(
    piece: str,
    current_user: dict = Depends(get_current_customer),
    db=Depends(get_database),
):
    """Return one registered product warranty with live progress."""
    try:
        return await _get_warranty_product(piece, current_user, db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in get_product_detail: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch product details")


@router.get("/api/warranty/all", include_in_schema=False)
async def get_all_registrations(
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
    skip: int = 0,
    limit: int = 50,
):
    """Backward-compatible admin registration listing."""
    try:
        registrations = await db[COLLECTIONS["registered_products"]].find().sort(
            "registered_at", -1
        ).skip(skip).limit(limit).to_list(None)
        total = await db[COLLECTIONS["registered_products"]].count_documents({})
        return {
            "registrations": [_registration_response(registration) for registration in registrations],
            "total": total,
            "skip": skip,
            "limit": limit,
        }
    except Exception as e:
        logger.exception("Error in get_all_registrations: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch registrations")


@router.get("/api/warranty/admin/product/{piece}", include_in_schema=False)
async def admin_get_product_detail(
    piece: str,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Backward-compatible admin warranty detail."""
    try:
        clean_piece = _clean_piece(piece)
        registration = await db[COLLECTIONS["registered_products"]].find_one({"piece": clean_piece})
        if not registration:
            raise HTTPException(status_code=404, detail="Product not registered")
        product = await db[COLLECTIONS["product_pieces"]].find_one({
            "_id": registration.get("piece_id")
        }) or await db[COLLECTIONS["product_pieces"]].find_one({"piece": clean_piece})
        return _registration_response(registration, product)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in admin_get_product_detail: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch product details")
