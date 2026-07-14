"""
Enquiry routes: /api/enquiry
- POST /
- GET /my
- GET /all
- GET /{id}
- PATCH /{id}/status
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from database import get_database
from config import COLLECTIONS
from schemas import EnquiryCreate, EnquiryStatusUpdate
from middleware.auth_guard import get_current_customer, get_current_admin
from services.customers import (
    PROFILE_REQUIRED_MESSAGE,
    get_customer_by_email,
    has_complete_profile,
    normalize_email,
)
from datetime import datetime
from bson import ObjectId
from pymongo import ReturnDocument
import logging
from services.warranty_eligibility import is_warranty_eligible

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/enquiry", tags=["enquiry"])
VALID_STATUSES = {"pending", "in_progress", "solved"}


def _validate_object_id(enquiry_id: str) -> ObjectId:
    if not ObjectId.is_valid(enquiry_id):
        raise HTTPException(status_code=400, detail="Invalid enquiry id")
    return ObjectId(enquiry_id)


def _issue_label(value) -> str:
    return getattr(value, "value", value)


def _customer_summary(customer: dict | None) -> dict | None:
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
    }


def _enquiry_response(enquiry: dict, include_description: bool = True, customer: dict | None = None) -> dict:
    response = {
        "id": str(enquiry["_id"]),
        "customer_id": str(enquiry.get("customer_id")) if enquiry.get("customer_id") else None,
        "customer_email": enquiry.get("customer_email"),
        "customer_phone": customer.get("phone") if customer else enquiry.get("customer_phone"),
        "customer": _customer_summary(customer) if customer else enquiry.get("customer"),
        "piece": enquiry.get("piece"),
        "item_name": enquiry.get("item_name"),
        "is_registered_product": enquiry.get("is_registered_product", True),
        "manual_handling_required": enquiry.get("manual_handling_required", False),
        "issue_type": enquiry.get("issue_type"),
        "status": enquiry.get("status"),
        "admin_note": enquiry.get("admin_note"),
        "created_at": enquiry.get("created_at"),
        "updated_at": enquiry.get("updated_at"),
    }
    if include_description:
        response["description"] = enquiry.get("description")
    return response


@router.post("/", response_model=dict)
async def create_enquiry(
    enquiry: EnquiryCreate,
    current_user: dict = Depends(get_current_customer),
    db = Depends(get_database)
):
    """Create a new enquiry"""
    try:
        email = normalize_email(current_user.get("email"))
        customer = await get_customer_by_email(db, email)
        if not has_complete_profile(customer):
            raise HTTPException(status_code=400, detail=PROFILE_REQUIRED_MESSAGE)

        clean_piece = enquiry.piece.strip()
        if not clean_piece:
            raise HTTPException(status_code=400, detail="Piece is required")
        if not enquiry.description.strip():
            raise HTTPException(status_code=400, detail="Description is required")

        product = await db[COLLECTIONS["product_pieces"]].find_one({"piece": clean_piece})
        if not product:
            raise HTTPException(status_code=404, detail="Piece not found. Check the piece number and try again.")

        # Registered products can only be used by their owning customer.
        registered_collection = db[COLLECTIONS["registered_products"]]
        registration = await registered_collection.find_one({"piece": clean_piece})
        if registration and registration.get("customer_id") != customer["_id"]:
            raise HTTPException(
                status_code=400,
                detail="This piece is registered to another customer."
            )
        if not registration and is_warranty_eligible(product):
            raise HTTPException(
                status_code=400,
                detail="This product is eligible for online warranty. Register the product before raising an enquiry.",
            )

        # Create enquiry record
        enquiry_record = {
            "customer_id": customer["_id"],
            "customer_email": email,
            "piece": clean_piece,
            "item_name": (registration or {}).get("item_name") or product.get("item_name") or enquiry.item_name.strip(),
            "is_registered_product": registration is not None,
            "manual_handling_required": registration is None,
            "issue_type": _issue_label(enquiry.issue_type),
            "description": enquiry.description.strip(),
            "status": "pending",
            "admin_note": None,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        enquiry_collection = db[COLLECTIONS["enquiries"]]
        result = await enquiry_collection.insert_one(enquiry_record)

        return {
            "message": "Enquiry submitted successfully",
            "enquiry": _enquiry_response({**enquiry_record, "_id": result.inserted_id}),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in create_enquiry: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create enquiry")


@router.get("/my")
async def get_my_enquiries(
    current_user: dict = Depends(get_current_customer),
    db = Depends(get_database)
):
    """Get all enquiries for current customer"""
    try:
        email = current_user.get("email")

        enquiry_collection = db[COLLECTIONS["enquiries"]]
        enquiries = await enquiry_collection.find(
            {"customer_email": email}
        ).sort("created_at", -1).to_list(None)

        return {
            "enquiries": [
                {
                    **_enquiry_response(e),
                }
                for e in enquiries
            ],
            "total": len(enquiries),
        }

    except Exception as e:
        logger.error(f"Error in get_my_enquiries: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch enquiries")


@router.get("/all")
async def get_all_enquiries(
    current_user: dict = Depends(get_current_admin),
    db = Depends(get_database),
    status: str = Query(None, pattern="^(pending|in_progress|solved)$"),
):
    """Get all enquiries (admin only)"""
    try:
        enquiry_collection = db[COLLECTIONS["enquiries"]]

        query = {}
        if status:
            query["status"] = status

        enquiries = await enquiry_collection.find(query).sort("created_at", -1).to_list(None)

        return {
            "enquiries": [
                {
                    **_enquiry_response(e),
                }
                for e in enquiries
            ],
            "total": len(enquiries),
        }

    except Exception as e:
        logger.error(f"Error in get_all_enquiries: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch enquiries")


@router.get("/{enquiry_id}")
async def get_enquiry_detail(
    enquiry_id: str,
    current_user: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """Get enquiry details (admin only)"""
    try:
        enquiry_collection = db[COLLECTIONS["enquiries"]]

        enquiry = await enquiry_collection.find_one({"_id": _validate_object_id(enquiry_id)})

        if not enquiry:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        customer = None
        customer_id = enquiry.get("customer_id")
        if customer_id:
            customer = await db[COLLECTIONS["customers"]].find_one({"_id": customer_id})
        if not customer and enquiry.get("customer_email"):
            customer = await db[COLLECTIONS["customers"]].find_one({
                "email": normalize_email(enquiry.get("customer_email")),
            })

        return _enquiry_response(enquiry, customer=customer)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_enquiry_detail: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch enquiry")


@router.patch("/{enquiry_id}/status")
async def update_enquiry_status(
    enquiry_id: str,
    update: EnquiryStatusUpdate,
    current_user: dict = Depends(get_current_admin),
    db = Depends(get_database)
):
    """Update enquiry status (admin only)"""
    try:
        enquiry_collection = db[COLLECTIONS["enquiries"]]

        status = _issue_label(update.status)
        if status not in VALID_STATUSES:
            raise HTTPException(status_code=400, detail="Invalid enquiry status")

        result = await enquiry_collection.find_one_and_update(
            {"_id": _validate_object_id(enquiry_id)},
            {
                "$set": {
                    "status": status,
                    "admin_note": update.admin_note.strip() if update.admin_note else None,
                    "updated_at": datetime.utcnow(),
                }
            },
            return_document=ReturnDocument.AFTER
        )

        if not result:
            raise HTTPException(status_code=404, detail="Enquiry not found")

        return {
            "message": "Enquiry updated successfully",
            "enquiry": _enquiry_response(result),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in update_enquiry_status: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update enquiry")
