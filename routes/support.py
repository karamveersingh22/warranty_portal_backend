"""
Support contacts: /api/support

Admins manage support team members (name, title, phone, email). Customers and
admins can read the active contacts to display in the support section.
"""

from datetime import datetime
import logging

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from pymongo import ReturnDocument

from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_admin, get_current_user
from models import SupportContactDocument
from schemas import SupportContactCreate, SupportContactUpdate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/support", tags=["support"])


def _validate_id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Invalid contact id")
    return ObjectId(value)


def _contact_response(contact: dict) -> dict:
    return {
        "id": str(contact["_id"]),
        "name": contact.get("name"),
        "title": contact.get("title", ""),
        "phone": contact.get("phone", ""),
        "email": contact.get("email", ""),
        "is_active": contact.get("is_active", True),
    }


@router.get("/contacts")
async def list_support_contacts(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_database),
):
    """List support contacts. Customers see only active ones; admins see all."""
    try:
        is_admin = current_user.get("role") == "admin"
        query = {} if is_admin else {"is_active": True}
        contacts = await db[COLLECTIONS["support_contacts"]].find(query).sort(
            "created_at", 1
        ).to_list(None)
        return {
            "contacts": [_contact_response(c) for c in contacts],
            "total": len(contacts),
        }
    except Exception as e:
        logger.exception("Error in list_support_contacts: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to fetch support contacts")


@router.post("/contacts")
async def create_support_contact(
    body: SupportContactCreate,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Create a support contact (admin only)."""
    try:
        now = datetime.utcnow()
        doc = SupportContactDocument(
            name=body.name,
            title=body.title or "",
            phone=body.phone or "",
            email=body.email or "",
            is_active=body.is_active,
            created_at=now,
            updated_at=now,
        ).to_mongo()
        result = await db[COLLECTIONS["support_contacts"]].insert_one(doc)
        return {
            "message": "Support contact added",
            "contact": _contact_response({**doc, "_id": result.inserted_id}),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in create_support_contact: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to add support contact")


@router.put("/contacts/{contact_id}")
async def update_support_contact(
    contact_id: str,
    body: SupportContactUpdate,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Update a support contact (admin only)."""
    try:
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            raise HTTPException(status_code=400, detail="No update fields provided")
        updates["updated_at"] = datetime.utcnow()
        result = await db[COLLECTIONS["support_contacts"]].find_one_and_update(
            {"_id": _validate_id(contact_id)},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        if not result:
            raise HTTPException(status_code=404, detail="Support contact not found")
        return {"message": "Support contact updated", "contact": _contact_response(result)}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in update_support_contact: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to update support contact")


@router.delete("/contacts/{contact_id}")
async def delete_support_contact(
    contact_id: str,
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Delete a support contact (admin only)."""
    try:
        result = await db[COLLECTIONS["support_contacts"]].delete_one({"_id": _validate_id(contact_id)})
        if not result.deleted_count:
            raise HTTPException(status_code=404, detail="Support contact not found")
        return {"message": "Support contact removed"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in delete_support_contact: %s", str(e))
        raise HTTPException(status_code=500, detail="Failed to remove support contact")
