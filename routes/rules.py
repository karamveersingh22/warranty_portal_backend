"""
Warranty rules routes: /api/rules

Admins can create, update, and deactivate rules. Customers can read active
rules only for categories of products registered to them. Warranty duration
values come only from active rules in MongoDB.
"""

from datetime import datetime
import logging
import re

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo import ReturnDocument

from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_admin, get_current_user
from models import WarrantyRuleDocument
from schemas import WarrantyRuleCreate, WarrantyRuleUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/rules", tags=["rules"])


def _clean_category(category: str) -> str:
    cleaned = category.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Category is required")
    return cleaned


def _rule_response(rule: dict) -> dict:
    return {
        "id": str(rule["_id"]),
        "category": rule.get("category"),
        "warranty_months": rule.get("warranty_months"),
        "is_active": rule.get("is_active", True),
        "terms": rule.get("terms", []),
        "created_at": rule.get("created_at"),
        "updated_at": rule.get("updated_at"),
    }


def _validate_rule_id(rule_id: str) -> ObjectId:
    if not ObjectId.is_valid(rule_id):
        raise HTTPException(status_code=400, detail="Invalid rule id")
    return ObjectId(rule_id)


def _clean_terms(terms: list) -> list:
    return [t.strip() for t in terms if t and t.strip()]


def _category_query(category: str) -> dict:
    return {"category": {"$regex": f"^{re.escape(category)}$", "$options": "i"}}


@router.get("/categories")
async def get_categories(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """Get distinct product categories from product_pieces for the dropdown."""
    try:
        categories = await db[COLLECTIONS["product_pieces"]].distinct("category")
        categories = sorted([c for c in categories if c and c.strip()])
        return {"categories": categories}
    except Exception as e:
        logger.exception("Error in get_categories: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch categories")


@router.get("/")
async def get_warranty_rules(
    include_inactive: bool = Query(False),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """Get admin rules or active rules for the customer's registered products."""
    try:
        if include_inactive and current_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="Admin access required")

        if current_user.get("role") == "admin":
            query = {} if include_inactive else {"is_active": True}
        else:
            customer_email = (current_user.get("email") or "").lower().strip()
            owned_categories = await db[COLLECTIONS["registered_products"]].distinct(
                "category",
                {"customer_email": customer_email},
            )
            owned_categories = sorted({
                category.strip()
                for category in owned_categories
                if isinstance(category, str) and category.strip()
            })
            if not owned_categories:
                return {"rules": [], "total": 0}

            query = {
                "is_active": True,
                "$or": [_category_query(category) for category in owned_categories],
            }

        rules = await db[COLLECTIONS["warranty_rules"]].find(query).sort(
            "category", 1
        ).to_list(None)

        return {
            "rules": [_rule_response(rule) for rule in rules],
            "total": len(rules),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in get_warranty_rules: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch rules")


@router.post("/", response_model=dict)
async def create_warranty_rule(
    rule: WarrantyRuleCreate,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Create a warranty rule."""
    try:
        rules_collection = db[COLLECTIONS["warranty_rules"]]
        category = _clean_category(rule.category)

        existing = await rules_collection.find_one(_category_query(category))
        if existing:
            raise HTTPException(
                status_code=400,
                detail=f"Rule for category '{category}' already exists",
            )

        now = datetime.utcnow()
        rule_document = WarrantyRuleDocument(
            category=category,
            warranty_months=rule.warranty_months,
            is_active=rule.is_active,
            terms=_clean_terms(rule.terms),
            created_at=now,
            updated_at=now,
        )
        rule_record = rule_document.to_mongo()
        result = await rules_collection.insert_one(rule_record)

        return {
            "message": "Warranty rule created successfully",
            "rule": _rule_response({**rule_record, "_id": result.inserted_id}),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in create_warranty_rule: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to create rule")


@router.put("/{rule_id}")
async def update_warranty_rule(
    rule_id: str,
    update: WarrantyRuleUpdate,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Update a warranty rule."""
    try:
        rules_collection = db[COLLECTIONS["warranty_rules"]]
        object_id = _validate_rule_id(rule_id)
        update_data = {key: value for key, value in update.model_dump().items() if value is not None}

        if not update_data:
            raise HTTPException(status_code=400, detail="No update fields provided")

        if "category" in update_data:
            category = _clean_category(update_data["category"])
            existing = await rules_collection.find_one({
                "_id": {"$ne": object_id},
                **_category_query(category),
            })
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Rule for category '{category}' already exists",
                )
            update_data["category"] = category

        if "terms" in update_data:
            update_data["terms"] = _clean_terms(update_data["terms"])

        update_data["updated_at"] = datetime.utcnow()
        result = await rules_collection.find_one_and_update(
            {"_id": object_id},
            {"$set": update_data},
            return_document=ReturnDocument.AFTER,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Rule not found")

        return {
            "message": "Warranty rule updated successfully",
            "rule": _rule_response(result),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in update_warranty_rule: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to update rule")


@router.delete("/{rule_id}")
async def deactivate_warranty_rule(
    rule_id: str,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Deactivate a warranty rule."""
    try:
        result = await db[COLLECTIONS["warranty_rules"]].find_one_and_update(
            {"_id": _validate_rule_id(rule_id)},
            {"$set": {"is_active": False, "updated_at": datetime.utcnow()}},
            return_document=ReturnDocument.AFTER,
        )

        if not result:
            raise HTTPException(status_code=404, detail="Rule not found")

        return {
            "message": "Warranty rule deactivated successfully",
            "rule": _rule_response(result),
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in deactivate_warranty_rule: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to deactivate rule")
