"""
Customer routes: /api/customer
- POST /profile
- GET /profile
- GET /all (admin)
- GET /{id} (admin)
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from database import get_database
from config import COLLECTIONS
from schemas import CustomerDeleteRequest, CustomerProfileCreate, CustomerProfileResponse, CustomerRegisterRequest
from middleware.auth_guard import get_current_customer, get_current_admin
from datetime import datetime
import logging
from bson import ObjectId

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/customer", tags=["customer"])


def _validate_object_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Invalid customer id")
    return ObjectId(value)


def _customer_response(customer: dict, registered_products: int = 0) -> dict:
    return {
        "id": str(customer["_id"]),
        "name": customer.get("name", ""),
        "email": customer.get("email", ""),
        "phone": customer.get("phone", ""),
        "address": customer.get("address", ""),
        "city": customer.get("city", ""),
        "state": customer.get("state", ""),
        "profile_complete": customer.get("profile_complete", False),
        "registered_products": registered_products,
        "created_at": customer.get("created_at"),
        "updated_at": customer.get("updated_at"),
    }


@router.post("/register", response_model=CustomerProfileResponse)
async def register_customer(
    registration: CustomerRegisterRequest,
    db = Depends(get_database)
):
    """Create a customer account before OTP login is allowed."""
    try:
        customers_collection = db[COLLECTIONS["customers"]]
        email = registration.email.lower().strip()

        existing = await customers_collection.find_one({"email": email})
        if existing and existing.get("profile_complete"):
            raise HTTPException(status_code=400, detail="Customer already registered. Please login.")

        customer_data = {
            "name": registration.name.strip(),
            "email": email,
            "phone": registration.phone.strip(),
            "address": registration.address.strip(),
            "city": registration.city.strip(),
            "state": (registration.state or "").strip(),
            "profile_complete": True,
            "feedback_submitted": False,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        }

        if existing:
            await customers_collection.update_one(
                {"_id": existing["_id"]},
                {"$set": customer_data}
            )
            customer_data["_id"] = existing["_id"]
            customer_data["created_at"] = existing.get("created_at", customer_data["created_at"])
        else:
            result = await customers_collection.insert_one(customer_data)
            customer_data["_id"] = result.inserted_id

        return CustomerProfileResponse(
            id=str(customer_data["_id"]),
            name=customer_data["name"],
            email=customer_data["email"],
            phone=customer_data["phone"],
            address=customer_data["address"],
            city=customer_data["city"],
            state=customer_data["state"],
            profile_complete=True,
            created_at=customer_data["created_at"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in register_customer: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to register customer")


@router.post("/profile", response_model=CustomerProfileResponse)
async def create_or_update_profile(
    profile: CustomerProfileCreate,
    current_user: dict = Depends(get_current_customer),
    db = Depends(get_database)
):
    """Create or update customer profile"""
    try:
        customers_collection = db[COLLECTIONS["customers"]]
        email = current_user.get("email")

        customer_data = {
            "name": profile.name,
            "email": email,
            "phone": profile.phone,
            "address": profile.address,
            "city": profile.city,
            "state": profile.state or "",
            "profile_complete": True,
            "updated_at": datetime.utcnow(),
        }

        result = await customers_collection.find_one_and_update(
            {"email": email},
            {
                "$set": customer_data,
                "$setOnInsert": {"created_at": datetime.utcnow()},
            },
            return_document=True,
            upsert=True
        )

        return CustomerProfileResponse(
            id=str(result["_id"]),
            name=result["name"],
            email=result["email"],
            phone=result.get("phone"),
            address=result["address"],
            city=result["city"],
            state=result["state"],
            profile_complete=result["profile_complete"],
            created_at=result.get("created_at"),
        )

    except Exception as e:
        logger.error(f"Error in create_or_update_profile: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to update profile")


@router.get("/profile", response_model=CustomerProfileResponse)
async def get_profile(
    current_user: dict = Depends(get_current_customer),
    db = Depends(get_database)
):
    """Get customer profile"""
    try:
        customers_collection = db[COLLECTIONS["customers"]]
        email = current_user.get("email")

        customer = await customers_collection.find_one({"email": email})

        if not customer:
            raise HTTPException(status_code=404, detail="Profile not found")

        return CustomerProfileResponse(
            id=str(customer["_id"]),
            name=customer.get("name", ""),
            email=customer["email"],
            phone=customer.get("phone"),
            address=customer.get("address", ""),
            city=customer.get("city", ""),
            state=customer.get("state", ""),
            profile_complete=customer.get("profile_complete", False),
            created_at=customer.get("created_at"),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_profile: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch profile")


# ==================== ADMIN ENDPOINTS ====================

@router.get("/all")
async def get_all_customers(
    current_user: dict = Depends(get_current_admin),
    db = Depends(get_database),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    search: str = Query(None),
):
    """Get all customers (admin only) with optional search"""
    try:
        customers_collection = db[COLLECTIONS["customers"]]

        query = {}
        if search:
            query = {
                "$or": [
                    {"name": {"$regex": search, "$options": "i"}},
                    {"email": {"$regex": search, "$options": "i"}},
                    {"city": {"$regex": search, "$options": "i"}},
                ]
            }

        total = await customers_collection.count_documents(query)
        customers = await customers_collection.find(query).sort(
            "created_at", -1
        ).skip(skip).limit(limit).to_list(None)

        # Get registration counts for each customer
        registered_collection = db[COLLECTIONS["registered_products"]]

        result = []
        for c in customers:
            reg_count = await registered_collection.count_documents({"customer_id": c["_id"]})
            result.append(_customer_response(c, reg_count))

        return {"customers": result, "total": total, "skip": skip, "limit": limit}

    except Exception as e:
        logger.error(f"Error in get_all_customers: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch customers")


@router.get("/{customer_id}")
async def get_customer_detail(
    customer_id: str,
    current_user: dict = Depends(get_current_admin),
    db = Depends(get_database),
):
    """Get one customer with registered products and enquiries (admin only)."""
    try:
        customer_object_id = _validate_object_id(customer_id)
        customers_collection = db[COLLECTIONS["customers"]]
        registered_collection = db[COLLECTIONS["registered_products"]]
        enquiries_collection = db[COLLECTIONS["enquiries"]]

        customer = await customers_collection.find_one({"_id": customer_object_id})
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        registrations = await registered_collection.find({
            "customer_id": customer_object_id
        }).sort("registered_at", -1).to_list(None)
        enquiries = await enquiries_collection.find({
            "customer_id": customer_object_id
        }).sort("created_at", -1).to_list(None)

        return {
            "customer": _customer_response(customer, len(registrations)),
            "products": [
                {
                    "id": str(product["_id"]),
                    "piece": product.get("piece"),
                    "item_name": product.get("item_name"),
                    "i_code": product.get("i_code"),
                    "category": product.get("category"),
                    "dealer_bill_number": product.get("dealer_bill_number"),
                    "dealer_bill_date": product.get("dealer_bill_date"),
                    "warranty_start": product.get("warranty_start"),
                    "warranty_end": product.get("warranty_end"),
                    "warranty_months": product.get("warranty_months"),
                    "status": product.get("status"),
                    "registered_at": product.get("registered_at"),
                }
                for product in registrations
            ],
            "enquiries": [
                {
                    "id": str(enquiry["_id"]),
                    "piece": enquiry.get("piece"),
                    "item_name": enquiry.get("item_name"),
                    "issue_type": enquiry.get("issue_type"),
                    "description": enquiry.get("description"),
                    "status": enquiry.get("status"),
                    "admin_note": enquiry.get("admin_note"),
                    "created_at": enquiry.get("created_at"),
                    "updated_at": enquiry.get("updated_at"),
                }
                for enquiry in enquiries
            ],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_customer_detail: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch customer")


@router.delete("/{customer_id}")
async def delete_customer_and_related_data(
    customer_id: str,
    body: CustomerDeleteRequest,
    current_user: dict = Depends(get_current_admin),
    db = Depends(get_database),
):
    """Permanently delete one customer and every customer-owned record."""
    try:
        customer_object_id = _validate_object_id(customer_id)
        customers_collection = db[COLLECTIONS["customers"]]
        customer = await customers_collection.find_one({"_id": customer_object_id})
        if not customer:
            raise HTTPException(status_code=404, detail="Customer not found")

        customer_email = (customer.get("email") or "").lower().strip()
        if body.confirmation_email.lower().strip() != customer_email:
            raise HTTPException(
                status_code=400,
                detail="Confirmation email does not match the selected customer.",
            )

        ownership_query = {
            "$or": [
                {"customer_id": customer_object_id},
                {"customer_email": customer_email},
            ]
        }
        deleted_counts = {}
        for collection_key in (
            "customer_feedbacks",
            "enquiries",
            "registration_requests",
            "registered_products",
        ):
            result = await db[COLLECTIONS[collection_key]].delete_many(ownership_query)
            deleted_counts[collection_key] = result.deleted_count

        otp_result = await db[COLLECTIONS["otp_sessions"]].delete_many({
            "email": customer_email,
            "role": "customer",
        })
        deleted_counts["otp_sessions"] = otp_result.deleted_count

        customer_result = await customers_collection.delete_one({"_id": customer_object_id})
        if customer_result.deleted_count != 1:
            raise HTTPException(status_code=500, detail="Customer profile could not be deleted")
        deleted_counts["customers"] = customer_result.deleted_count

        logger.warning(
            "Admin %s permanently deleted customer %s (%s) and related data: %s",
            current_user.get("email"),
            customer_id,
            customer_email,
            deleted_counts,
        )
        return {
            "message": "Customer and all related customer data were permanently deleted.",
            "customer_id": customer_id,
            "customer_email": customer_email,
            "deleted_counts": deleted_counts,
            "product_pieces_preserved": True,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to delete customer %s and related data: %s", customer_id, str(e))
        raise HTTPException(status_code=500, detail="Failed to delete customer and related data")
