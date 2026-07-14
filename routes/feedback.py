"""Mandatory per-piece customer feedback and admin search."""

from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pymongo.errors import DuplicateKeyError

from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_admin, get_current_customer_identity
from models import CustomerFeedbackDocument
from schemas import CustomerFeedbackCreate

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


def _response(document: dict) -> dict:
    return {
        "id": str(document["_id"]),
        "customer_id": str(document.get("customer_id")),
        "customer_email": document.get("customer_email"),
        "customer_name": document.get("customer_name"),
        "piece": document.get("piece"),
        "item_name": document.get("item_name"),
        "dealer_name": document.get("dealer_name"),
        "answers": document.get("answers", {}),
        "submitted_at": document.get("submitted_at"),
    }


@router.post("")
async def submit_feedback(
    body: CustomerFeedbackCreate,
    current_user: dict = Depends(get_current_customer_identity),
    db=Depends(get_database),
):
    email = (current_user.get("email") or "").lower().strip()
    piece = body.piece.strip()
    customer = await db[COLLECTIONS["customers"]].find_one({"email": email})
    if not customer:
        raise HTTPException(status_code=404, detail="Customer account not found")

    request = await db[COLLECTIONS["registration_requests"]].find_one({
        "customer_id": customer["_id"],
        "piece": piece,
        "feedback_required": True,
    })
    if not request:
        raise HTTPException(status_code=400, detail="No feedback is required for this piece")
    if request.get("feedback_submitted"):
        raise HTTPException(status_code=400, detail="Feedback has already been submitted for this piece")

    product = await db[COLLECTIONS["product_pieces"]].find_one({"_id": request.get("piece_id")}) or {}
    answers = body.model_dump(exclude={"piece"})
    document = CustomerFeedbackDocument(
        customer_id=customer["_id"],
        customer_email=email,
        customer_name=customer.get("name", ""),
        piece=piece,
        item_name=request.get("item_name", ""),
        dealer_name=product.get("dealer_name", ""),
        answers=answers,
        submitted_at=datetime.utcnow(),
    ).to_mongo()

    try:
        result = await db[COLLECTIONS["customer_feedbacks"]].insert_one(document)
    except DuplicateKeyError:
        raise HTTPException(status_code=400, detail="Feedback has already been submitted for this piece")

    await db[COLLECTIONS["registration_requests"]].update_one(
        {"_id": request["_id"]},
        {"$set": {"feedback_submitted": True, "feedback_submitted_at": datetime.utcnow()}},
    )
    # Convenience summary only; per-piece enforcement remains on registration_requests.
    await db[COLLECTIONS["customers"]].update_one(
        {"_id": customer["_id"]},
        {"$set": {"feedback_submitted": True, "updated_at": datetime.utcnow()}},
    )
    return {"message": "Thank you for your feedback", "feedback": _response({**document, "_id": result.inserted_id})}


@router.get("")
async def list_feedback(
    q: str | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(25, ge=1, le=100),
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    query = {}
    if q and q.strip():
        pattern = {"$regex": re.escape(q.strip()), "$options": "i"}
        query = {"$or": [{"piece": pattern}, {"customer_email": pattern}, {"customer_name": pattern}, {"item_name": pattern}, {"dealer_name": pattern}]}
    collection = db[COLLECTIONS["customer_feedbacks"]]
    total = await collection.count_documents(query)
    documents = await collection.find(query).sort("submitted_at", -1).skip(skip).limit(limit).to_list(None)
    return {"feedbacks": [_response(document) for document in documents], "total": total, "skip": skip, "limit": limit}
