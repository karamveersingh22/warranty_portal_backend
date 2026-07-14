"""
Admin registration-request review routes: /api/registrations

Customers submit registration requests (see routes/warranty.py). Admins review
each request - inspecting buyer, dealer, distributor, item, company dispatch,
and customer-supplied dealer invoice details. Product age is measured from the
dealer invoice date to the request date.
(creating the active warranty) or decline (notifying the buyer).
"""

from datetime import datetime
import logging
from typing import Any, Dict, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import DuplicateKeyError
from dateutil.relativedelta import relativedelta

from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_admin
from models import RegisteredProductDocument
from schemas import RegistrationDeclineRequest, FlagDaysUpdate
from services.app_settings import get_flag_days, set_flag_days
from services.warranty_calculator import calculate_warranty

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/registrations", tags=["registrations"])


def _validate_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Invalid request id")
    return ObjectId(value)


def _object_id_to_str(value: Any) -> Optional[str]:
    if isinstance(value, ObjectId):
        return str(value)
    return value


def _address_line(*parts: Optional[str]) -> str:
    return " ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())


def _age(requested_at: Optional[datetime], bill_date: Optional[datetime], flag_days: int) -> Dict[str, Any]:
    if not requested_at or not bill_date:
        return {"days_old": None, "months_old": None, "is_flagged": False}
    delta = requested_at - bill_date
    days_old = delta.days
    months_old = round(days_old / 30.0, 1)
    return {
        "days_old": days_old,
        "months_old": months_old,
        "is_flagged": days_old >= flag_days,
    }


async def _request_detail(db, req: dict, flag_days: int) -> Dict[str, Any]:
    customer = await db[COLLECTIONS["customers"]].find_one({"_id": req.get("customer_id")})
    product = await db[COLLECTIONS["product_pieces"]].find_one({"_id": req.get("piece_id")}) \
        or await db[COLLECTIONS["product_pieces"]].find_one({"piece": req.get("piece")})
    product = product or {}

    age = _age(req.get("requested_at"), req.get("dealer_bill_date"), flag_days)

    return {
        "id": str(req.get("_id")),
        "status": req.get("status"),
        "requested_at": req.get("requested_at"),
        "reviewed_at": req.get("reviewed_at"),
        "reviewed_by": req.get("reviewed_by"),
        "decline_reason": req.get("decline_reason"),
        "warranty_months": req.get("warranty_months"),
        **age,
        "buyer": {
            "id": _object_id_to_str(req.get("customer_id")),
            "name": customer.get("name") if customer else None,
            "email": req.get("customer_email"),
            "phone": customer.get("phone") if customer else None,
            "address": customer.get("address") if customer else None,
            "city": customer.get("city") if customer else None,
            "state": customer.get("state") if customer else None,
        },
        "dealer": {
            "code": product.get("dealer_code"),
            "name": product.get("dealer_name"),
            "address": _address_line(product.get("dealer_add1"), product.get("dealer_add2")),
            "city": product.get("dealer_city"),
            "state": product.get("dealer_state"),
            "phone": product.get("dealer_phone"),
        },
        "distributor": {
            "code": product.get("distributor_code"),
            "name": product.get("distributor_name"),
            "address": _address_line(product.get("distributor_add1"), product.get("distributor_add2")),
            "city": product.get("distributor_city"),
        },
        "item": {
            "piece": req.get("piece"),
            "i_code": req.get("i_code"),
            "item_name": req.get("item_name"),
            "category": req.get("category"),
            "size": req.get("size"),
        },
        "dealer_bill": {
            "bill_number": req.get("dealer_bill_number"),
            "bill_date": req.get("dealer_bill_date"),
            "registration_date": req.get("requested_at"),
        },
        "company_dispatch": {
            "bill_number": req.get("bill") or product.get("bill"),
            "bill_date": req.get("bill_date") or product.get("bill_date"),
        },
    }


@router.get("")
@router.get("/")
async def list_registration_requests(
    status: Optional[str] = Query("pending", pattern="^(pending|approved|declined|all)$"),
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """List registration requests for admin review. Defaults to pending."""
    try:
        flag_days = await get_flag_days(db)
        query: Dict[str, Any] = {}
        if status and status != "all":
            query["status"] = status

        requests = await db[COLLECTIONS["registration_requests"]].find(query).sort(
            "requested_at", -1
        ).to_list(None)

        items = [await _request_detail(db, req, flag_days) for req in requests]
        pending_count = await db[COLLECTIONS["registration_requests"]].count_documents({"status": "pending"})
        flagged_count = sum(1 for item in items if item.get("is_flagged") and item.get("status") == "pending")

        return {
            "requests": items,
            "total": len(items),
            "pending_count": pending_count,
            "flagged_count": flagged_count,
            "old_product_flag_days": flag_days,
        }
    except Exception as e:
        logger.exception("Error in list_registration_requests: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch registration requests")


@router.get("/settings")
async def get_registration_settings(
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Return the configurable product-age flag threshold."""
    return {"old_product_flag_days": await get_flag_days(db)}


@router.put("/settings")
async def update_registration_settings(
    body: FlagDaysUpdate,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Update the product-age flag threshold (in days)."""
    try:
        days = await set_flag_days(db, body.old_product_flag_days)
        return {"message": "Settings updated", "old_product_flag_days": days}
    except Exception as e:
        logger.exception("Error in update_registration_settings: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to update settings")


@router.post("/{request_id}/approve")
async def approve_registration_request(
    request_id: str,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Approve a pending request and create the active warranty registration."""
    try:
        req = await db[COLLECTIONS["registration_requests"]].find_one({"_id": _validate_id(request_id)})
        if not req:
            raise HTTPException(status_code=404, detail="Registration request not found")
        if req.get("status") != "pending":
            raise HTTPException(status_code=400, detail=f"Request is already {req.get('status')}")

        already = await db[COLLECTIONS["registered_products"]].find_one({"piece": req.get("piece")})
        if already:
            await db[COLLECTIONS["registration_requests"]].update_one(
                {"_id": req["_id"]},
                {"$set": {
                    "status": "declined",
                    "decline_reason": "This piece was already registered by another customer.",
                    "reviewed_by": current_user.get("email"),
                    "reviewed_at": datetime.utcnow(),
                }},
            )
            raise HTTPException(status_code=400, detail="This piece is already registered. Request marked declined.")

        warranty_months = req.get("warranty_months")
        dealer_bill_number = (req.get("dealer_bill_number") or "").strip()
        dealer_bill_date = req.get("dealer_bill_date")
        if not dealer_bill_number or not dealer_bill_date:
            raise HTTPException(
                status_code=400,
                detail="Dealer bill number and dealer bill date are required. Decline this legacy request and ask the customer to submit it again.",
            )
        warranty_start = dealer_bill_date
        warranty_end = warranty_start + relativedelta(months=warranty_months)
        warranty = calculate_warranty(warranty_start, warranty_end)

        registration_doc = RegisteredProductDocument(
            customer_id=req["customer_id"],
            customer_email=req["customer_email"],
            piece_id=req["piece_id"],
            piece=req["piece"],
            item_name=req.get("item_name", ""),
            i_code=req.get("i_code", ""),
            category=req.get("category", ""),
            dealer_bill_number=dealer_bill_number,
            dealer_bill_date=dealer_bill_date,
            warranty_rule_id=req.get("warranty_rule_id"),
            warranty_start=warranty_start,
            warranty_end=warranty_end,
            warranty_months=warranty_months,
            status=warranty["status"],
            registered_at=datetime.utcnow(),
        )

        try:
            await db[COLLECTIONS["registered_products"]].insert_one(registration_doc.to_mongo())
        except DuplicateKeyError:
            raise HTTPException(status_code=400, detail="This piece is already registered")

        await db[COLLECTIONS["registration_requests"]].update_one(
            {"_id": req["_id"]},
            {"$set": {
                "status": "approved",
                "reviewed_by": current_user.get("email"),
                "reviewed_at": datetime.utcnow(),
            }},
        )

        return {"message": "Registration request approved", "piece": req.get("piece")}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in approve_registration_request: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to approve request")


@router.post("/{request_id}/decline")
async def decline_registration_request(
    request_id: str,
    body: RegistrationDeclineRequest = RegistrationDeclineRequest(),
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Decline a pending registration request."""
    try:
        req = await db[COLLECTIONS["registration_requests"]].find_one({"_id": _validate_id(request_id)})
        if not req:
            raise HTTPException(status_code=404, detail="Registration request not found")
        if req.get("status") != "pending":
            raise HTTPException(status_code=400, detail=f"Request is already {req.get('status')}")

        reason = (body.reason or "").strip() if body else ""
        await db[COLLECTIONS["registration_requests"]].update_one(
            {"_id": req["_id"]},
            {"$set": {
                "status": "declined",
                "decline_reason": reason or None,
                "reviewed_by": current_user.get("email"),
                "reviewed_at": datetime.utcnow(),
            }},
        )

        return {"message": "Registration request declined", "piece": req.get("piece")}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in decline_registration_request: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to decline request")
