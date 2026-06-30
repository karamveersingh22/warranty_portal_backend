"""Remove leftover dummy/test customers and all their linked records.

Matches customers whose `name` (trimmed, case-insensitive) is one of the
curated DUMMY_NAMES below, then cascades deletion to their registered products,
registration requests, and enquiries so nothing is left orphaned.

Read-only by default (preview). Pass --apply to actually delete.

Usage:
    cd backend
    python scripts/cleanup_dummy_customers.py            # preview only
    python scripts/cleanup_dummy_customers.py --apply    # actually delete
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from config import COLLECTIONS, get_settings

# Exact customer names to treat as dummy/test data (matched case-insensitively
# after trimming). Keep this list curated and explicit so a real customer is
# never matched by accident.
DUMMY_NAMES = ["c1", "c2", "j1", "a1", "n/a", "john doe"]

LINKED_COLLECTIONS = ["registered_products", "registration_requests", "enquiries"]


async def main(apply: bool):
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.database_name]

    print(f"Mode: {'APPLY (deleting)' if apply else 'PREVIEW (no changes)'}")
    print(f"Database: {settings.database_name}")
    print("=" * 70)

    # Find matching customers. We pull all customers and filter in Python so the
    # trim + case-insensitive comparison is exact and easy to audit.
    customers_coll = db[COLLECTIONS["customers"]]
    matched = []
    async for doc in customers_coll.find({}, {"name": 1, "email": 1}):
        name = (doc.get("name") or "").strip().lower()
        if name in DUMMY_NAMES:
            matched.append(doc)

    if not matched:
        print("No dummy customers matched. Nothing to do.")
        client.close()
        return

    print(f"Matched {len(matched)} dummy customer(s):\n")

    deleted_summary = {"customers": 0}
    for coll in LINKED_COLLECTIONS:
        deleted_summary[coll] = 0

    for cust in matched:
        cust_id = cust["_id"]
        email = (cust.get("email") or "").lower().strip()
        print(f"- name={cust.get('name')!r}  email={email!r}  _id={cust_id}")

        # Build a filter that catches links by either customer_id or customer_email.
        link_filter = {"$or": [{"customer_id": cust_id}, {"customer_email": email}]}

        for coll_key in LINKED_COLLECTIONS:
            coll = db[COLLECTIONS[coll_key]]
            count = await coll.count_documents(link_filter)
            print(f"    {coll_key}: {count} record(s)")
            if apply and count:
                res = await coll.delete_many(link_filter)
                deleted_summary[coll_key] += res.deleted_count

        if apply:
            res = await customers_coll.delete_one({"_id": cust_id})
            deleted_summary["customers"] += res.deleted_count

    print("=" * 70)
    if apply:
        print("Deleted:")
        for k, v in deleted_summary.items():
            print(f"  {k}: {v}")
    else:
        print("Preview only — nothing was deleted. Re-run with --apply to delete.")

    client.close()


if __name__ == "__main__":
    apply = "--apply" in sys.argv
    asyncio.run(main(apply))
