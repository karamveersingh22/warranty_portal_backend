"""
Seed MongoDB with DBF product data plus a small demo workflow.

Run from the backend folder:
    python scripts/seed_sample_data.py
"""

import argparse
import asyncio
from datetime import datetime
import os
from pathlib import Path
import sys
from dateutil.relativedelta import relativedelta

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(BACKEND_DIR))

from config import COLLECTIONS, get_settings  # noqa: E402
from database import close_mongo_connection, connect_to_mongo, get_database  # noqa: E402
from services.dbf_parser import (  # noqa: E402
    join_records,
    parse_booksale_dbf,
    parse_serials_dbf,
    upsert_product_pieces,
)
from services.warranty_calculator import calculate_warranty  # noqa: E402

DEMO_CUSTOMER = {
    "name": "Demo Customer",
    "email": "demo.customer@example.com",
    "phone": "9999999999",
    "address": "Demo Address",
    "city": "Ludhiana",
    "state": "Punjab",
    "profile_complete": True,
}


async def seed_demo_customer(db, demo_email: str):
    customers = db[COLLECTIONS["customers"]]
    now = datetime.utcnow()
    email = demo_email.lower().strip()
    customer_data = {**DEMO_CUSTOMER, "email": email}

    await customers.update_one(
        {"email": email},
        {
            "$set": {**customer_data, "updated_at": now},
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    return await customers.find_one({"email": email})


async def seed_demo_registration_and_enquiry(db, customer):
    pieces = db[COLLECTIONS["product_pieces"]]
    registrations = db[COLLECTIONS["registered_products"]]
    enquiries = db[COLLECTIONS["enquiries"]]
    rules = db[COLLECTIONS["warranty_rules"]]

    product = await pieces.find_one({"item_name": {"$regex": "MATTRESS", "$options": "i"}})
    if not product:
        product = await pieces.find_one({})
    if not product:
        return None

    piece = product["piece"]
    item_name = (product.get("item_name") or "").upper()
    active_rules = await rules.find({"is_active": True}).to_list(None)
    rule = next(
        (
            active_rule
            for active_rule in active_rules
            if (active_rule.get("category") or "").upper() in item_name
        ),
        None,
    )
    if not rule:
        return None

    warranty_months = rule["warranty_months"]
    warranty_start = datetime.utcnow()
    warranty_end = warranty_start + relativedelta(months=warranty_months)
    warranty_info = calculate_warranty(warranty_start, warranty_end)

    registration = {
        "customer_id": customer["_id"],
        "customer_email": customer["email"],
        "piece": piece,
        "item_name": product.get("item_name"),
        "i_code": product.get("i_code"),
        "warranty_rule_id": rule["_id"] if rule else None,
        "category": rule["category"],
        "warranty_start": warranty_start,
        "warranty_end": warranty_end,
        "warranty_months": warranty_months,
        "status": warranty_info["status"],
        "registered_at": warranty_start,
    }

    await registrations.update_one(
        {"piece": piece},
        {"$setOnInsert": registration},
        upsert=True,
    )

    await enquiries.update_one(
        {"piece": piece, "customer_email": customer["email"], "issue_type": "other"},
        {
            "$setOnInsert": {
                "customer_id": customer["_id"],
                "customer_email": customer["email"],
                "piece": piece,
                "item_name": product.get("item_name"),
                "issue_type": "other",
                "description": "Demo enquiry for route and dashboard testing.",
                "status": "pending",
                "admin_note": None,
                "created_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
    )

    return product


async def main():
    parser = argparse.ArgumentParser(description="Seed warranty portal sample data.")
    parser.add_argument("--booksale", default=str(PROJECT_DIR / "BOOKSALE.dbf"))
    parser.add_argument("--serials", default=str(PROJECT_DIR / "SERIALS.dbf"))
    parser.add_argument("--limit", type=int, default=0, help="Optional serial row limit for quick tests.")
    parser.add_argument(
        "--demo-email",
        default=DEMO_CUSTOMER["email"],
        help="Customer email to seed for frontend login testing.",
    )
    args = parser.parse_args()

    os.chdir(BACKEND_DIR)
    settings = get_settings()
    await connect_to_mongo(settings.mongodb_url, settings.database_name)
    db = await get_database()

    try:
        print("Parsing DBF files...")
        booksale, booksale_failed, booksale_rows = parse_booksale_dbf(args.booksale)
        serials, serials_failed = parse_serials_dbf(args.serials)
        if args.limit:
            serials = serials[:args.limit]

        joined, join_failed = join_records(serials, booksale)
        import_report = await upsert_product_pieces(db, joined)

        customer = await seed_demo_customer(db, args.demo_email)
        demo_product = await seed_demo_registration_and_enquiry(db, customer)

        failed_rows = booksale_failed + serials_failed + join_failed + import_report.failed_rows
        batch = {
            "uploaded_by": "seed_script",
            "uploaded_at": datetime.utcnow(),
            "booksale_rows": booksale_rows,
            "serials_rows": len(serials),
            "pieces_inserted": import_report.inserted_count,
            "pieces_updated": import_report.updated_count,
            "pieces_failed": len(failed_rows),
            "failed_rows": failed_rows[:10],
            "source": "seed_sample_data.py",
        }
        result = await db[COLLECTIONS["import_batches"]].insert_one(batch)

        print("\nSeed complete.")
        print(f"Import batch: {result.inserted_id}")
        print(f"BOOKSALE rows: {booksale_rows}")
        print(f"SERIALS rows: {len(serials)}")
        print(f"Pieces inserted: {import_report.inserted_count}")
        print(f"Pieces updated: {import_report.updated_count}")
        print(f"Pieces skipped: {import_report.ignored_count}")
        print(f"Failed rows: {batch['pieces_failed']}")
        print(f"Demo customer: {customer['email']}")
        if demo_product:
            print(f"Demo registered piece: {demo_product.get('piece')} - {demo_product.get('item_name')}")
        print(f"Admin user: {settings.admin_email.lower().strip()}")
    finally:
        await close_mongo_connection()


if __name__ == "__main__":
    asyncio.run(main())
