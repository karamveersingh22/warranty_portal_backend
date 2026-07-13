"""Profile-city dealer locator backed by BOOKSALE dealer traceability data."""

import re

from fastapi import APIRouter, Depends, HTTPException

from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_customer

router = APIRouter(prefix="/api/dealers", tags=["dealers"])


def _response(item: dict) -> dict:
    result = {
        "code": item.get("code"),
        "name": item.get("name", ""),
        "address": ", ".join(part for part in (item.get("address_1", ""), item.get("address_2", "")) if part),
        "city": item.get("city", ""),
        "state": item.get("state", ""),
        "phone": item.get("phone", ""),
    }
    return result


@router.get("/nearby")
async def list_nearby_dealers(
    current_user: dict = Depends(get_current_customer),
    db=Depends(get_database),
):
    """Return only dealers in the signed-in customer's profile city."""
    customer = await db[COLLECTIONS["customers"]].find_one({"email": current_user["email"]})
    city = (customer or {}).get("city", "").strip()
    if not city:
        raise HTTPException(status_code=400, detail="Add your city to your profile to find nearby dealers")

    query = {
        "dealer_name": {"$exists": True, "$nin": ["", None]},
        "dealer_city": {"$regex": f"^{re.escape(city)}$", "$options": "i"},
    }
    pipeline = [
        {"$match": query},
        {"$group": {"_id": {
            "code": "$dealer_code", "name": "$dealer_name", "address_1": "$dealer_add1",
            "address_2": "$dealer_add2", "city": "$dealer_city", "state": "$dealer_state", "phone": "$dealer_phone",
        }}},
        {"$project": {"_id": 0, "code": "$_id.code", "name": "$_id.name", "address_1": "$_id.address_1", "address_2": "$_id.address_2", "city": "$_id.city", "state": "$_id.state", "phone": "$_id.phone"}},
        {"$sort": {"city": 1, "name": 1}},
        {"$limit": 500},
    ]
    dealers = await db[COLLECTIONS["product_pieces"]].aggregate(pipeline).to_list(500)
    results = [_response(item) for item in dealers]
    return {"city": city, "state": (customer or {}).get("state", ""), "dealers": results, "total": len(results)}
