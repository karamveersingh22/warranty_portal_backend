"""
Admin utility routes: /api/admin
"""

from fastapi import APIRouter, Depends, HTTPException
from config import COLLECTIONS
from database import get_database
from middleware.auth_guard import get_current_admin
from services.warranty_calculator import calculate_warranty
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/stats")
async def get_admin_stats(
    current_user: dict = Depends(get_current_admin),
    db=Depends(get_database),
):
    """Return live portal counts for the admin dashboard."""
    try:
        product_pieces = db[COLLECTIONS["product_pieces"]]
        customers = db[COLLECTIONS["customers"]]
        registered_products = db[COLLECTIONS["registered_products"]]
        enquiries = db[COLLECTIONS["enquiries"]]
        import_batches = db[COLLECTIONS["import_batches"]]

        pending_enquiries = await enquiries.count_documents({"status": "pending"})
        in_progress_enquiries = await enquiries.count_documents({"status": "in_progress"})
        solved_enquiries = await enquiries.count_documents({"status": "solved"})
        active_warranties = 0
        expired_warranties = 0
        warranty_docs = await registered_products.find(
            {},
            {"warranty_start": 1, "warranty_end": 1, "status": 1}
        ).to_list(None)
        for warranty in warranty_docs:
            if warranty.get("warranty_start") and warranty.get("warranty_end"):
                live = calculate_warranty(warranty["warranty_start"], warranty["warranty_end"])
                if live["status"] == "expired":
                    expired_warranties += 1
                else:
                    active_warranties += 1
            elif warranty.get("status") == "expired":
                expired_warranties += 1
            else:
                active_warranties += 1

        last_import = await import_batches.find_one(sort=[("uploaded_at", -1)])
        recent_enquiries = await enquiries.find().sort("created_at", -1).limit(5).to_list(None)
        recent_imports = await import_batches.find().sort("uploaded_at", -1).limit(5).to_list(None)

        return {
            "total_pieces": await product_pieces.count_documents({}),
            "total_customers": await customers.count_documents({"profile_complete": True}),
            "total_registered_products": await registered_products.count_documents({}),
            "total_enquiries": await enquiries.count_documents({}),
            "pending_enquiries": pending_enquiries,
            "in_progress_enquiries": in_progress_enquiries,
            "solved_enquiries": solved_enquiries,
            "active_warranties": active_warranties,
            "expired_warranties": expired_warranties,
            "unregistered_pieces": max(
                await product_pieces.count_documents({}) - await registered_products.count_documents({}),
                0,
            ),
            "last_import": {
                "uploaded_at": last_import.get("uploaded_at"),
                "booksale_rows": last_import.get("booksale_rows", 0),
                "serials_rows": last_import.get("serials_rows", 0),
                "pieces_inserted": last_import.get("pieces_inserted", 0),
                "pieces_updated": last_import.get("pieces_updated", 0),
                "pieces_failed": last_import.get("pieces_failed", 0),
            } if last_import else None,
            "recent_enquiries": [
                {
                    "id": str(enquiry["_id"]),
                    "customer_email": enquiry.get("customer_email"),
                    "piece": enquiry.get("piece"),
                    "item_name": enquiry.get("item_name"),
                    "issue_type": enquiry.get("issue_type"),
                    "status": enquiry.get("status"),
                    "created_at": enquiry.get("created_at"),
                }
                for enquiry in recent_enquiries
            ],
            "recent_imports": [
                {
                    "id": str(batch["_id"]),
                    "uploaded_by": batch.get("uploaded_by"),
                    "uploaded_at": batch.get("uploaded_at"),
                    "booksale_rows": batch.get("booksale_rows", 0),
                    "serials_rows": batch.get("serials_rows", 0),
                    "pieces_inserted": batch.get("pieces_inserted", 0),
                    "pieces_updated": batch.get("pieces_updated", 0),
                    "pieces_failed": batch.get("pieces_failed", 0),
                    "source": batch.get("source"),
                }
                for batch in recent_imports
            ],
        }
    except Exception as exc:
        logger.exception("Error fetching admin stats: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to fetch admin stats")
