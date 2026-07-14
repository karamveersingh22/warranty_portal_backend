"""Admin-managed onboarding terms and permanent customer acceptance."""

from datetime import datetime

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query

from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_admin, get_current_customer_identity, get_current_user
from models import OnboardingTermDocument
from schemas import OnboardingTermCreate, OnboardingTermsAccept, OnboardingTermsReorder, OnboardingTermUpdate

router = APIRouter(prefix="/api/onboarding-terms", tags=["onboarding-terms"])


def _id(value: str) -> ObjectId:
    if not ObjectId.is_valid(value):
        raise HTTPException(status_code=400, detail="Invalid term id")
    return ObjectId(value)


def _response(term: dict) -> dict:
    return {"id": str(term["_id"]), "text": term["text"], "order": term["order"], "created_at": term.get("created_at"), "updated_at": term.get("updated_at")}


@router.get("")
async def list_terms(current_user: dict = Depends(get_current_user), db=Depends(get_database)):
    terms = await db[COLLECTIONS["onboarding_terms"]].find().sort("order", 1).to_list(None)
    return {"terms": [_response(term) for term in terms], "total": len(terms)}


@router.post("")
async def create_term(body: OnboardingTermCreate, current_user: dict = Depends(get_current_admin), db=Depends(get_database)):
    collection = db[COLLECTIONS["onboarding_terms"]]
    last = await collection.find_one(sort=[("order", -1)])
    now = datetime.utcnow()
    document = OnboardingTermDocument(text=body.text, order=(last.get("order", 0) if last else 0) + 1, created_at=now, updated_at=now).to_mongo()
    result = await collection.insert_one(document)
    return {"message": "Term created", "term": _response({**document, "_id": result.inserted_id})}


@router.put("/{term_id}")
async def update_term(term_id: str, body: OnboardingTermUpdate, current_user: dict = Depends(get_current_admin), db=Depends(get_database)):
    result = await db[COLLECTIONS["onboarding_terms"]].find_one_and_update({"_id": _id(term_id)}, {"$set": {"text": body.text.strip(), "updated_at": datetime.utcnow()}}, return_document=True)
    if not result:
        raise HTTPException(status_code=404, detail="Term not found")
    return {"message": "Term updated", "term": _response(result)}


@router.put("/reorder/all")
async def reorder_terms(body: OnboardingTermsReorder, current_user: dict = Depends(get_current_admin), db=Depends(get_database)):
    collection = db[COLLECTIONS["onboarding_terms"]]
    current = await collection.find().to_list(None)
    current_ids = {str(term["_id"]) for term in current}
    if len(body.term_ids) != len(set(body.term_ids)) or set(body.term_ids) != current_ids:
        raise HTTPException(status_code=400, detail="Reorder list must contain every term exactly once")
    # Use temporary negative values to avoid collisions with the unique order index.
    for position, term_id in enumerate(body.term_ids, 1):
        await collection.update_one({"_id": _id(term_id)}, {"$set": {"order": -position}})
    now = datetime.utcnow()
    for position, term_id in enumerate(body.term_ids, 1):
        await collection.update_one({"_id": _id(term_id)}, {"$set": {"order": position, "updated_at": now}})
    return {"message": "Terms reordered"}


@router.delete("/{term_id}")
async def delete_term(term_id: str, confirm: bool = Query(False), current_user: dict = Depends(get_current_admin), db=Depends(get_database)):
    if not confirm:
        raise HTTPException(status_code=400, detail="Deletion requires explicit confirmation")
    collection = db[COLLECTIONS["onboarding_terms"]]
    term = await collection.find_one({"_id": _id(term_id)})
    if not term:
        raise HTTPException(status_code=404, detail="Term not found")
    await collection.delete_one({"_id": term["_id"]})
    remaining = await collection.find().sort("order", 1).to_list(None)
    for position, item in enumerate(remaining, 1):
        await collection.update_one({"_id": item["_id"]}, {"$set": {"order": position}})
    return {"message": "Term permanently deleted"}


@router.post("/accept")
async def accept_terms(body: OnboardingTermsAccept, current_user: dict = Depends(get_current_customer_identity), db=Depends(get_database)):
    terms = await db[COLLECTIONS["onboarding_terms"]].find().sort("order", 1).to_list(None)
    if not terms:
        raise HTTPException(status_code=400, detail="Terms and conditions have not been configured yet")
    required_ids = [str(term["_id"]) for term in terms]
    if len(body.term_ids) != len(set(body.term_ids)) or set(body.term_ids) != set(required_ids):
        raise HTTPException(status_code=400, detail="You need to accept all terms and conditions to move further")
    email = (current_user.get("email") or "").lower().strip()
    result = await db[COLLECTIONS["customers"]].update_one({"email": email, "terms_required": True}, {"$set": {"onboarding_terms_accepted": True, "onboarding_terms_accepted_at": datetime.utcnow(), "onboarding_terms_snapshot": [{"term_id": str(term["_id"]), "text": term["text"], "order": term["order"]} for term in terms], "updated_at": datetime.utcnow()}})
    if result.matched_count != 1:
        raise HTTPException(status_code=404, detail="Customer account not found")
    return {"message": "Terms and conditions accepted"}
