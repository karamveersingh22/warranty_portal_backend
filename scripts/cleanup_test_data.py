#!/usr/bin/env python
"""
Cleanup script to remove all test data from the database.
Preserves: warranty_rules, support_contacts, catalogue_settings, catalogue_files, app_settings, admin_users

Usage:
    python cleanup_test_data.py --preview    # Show what would be deleted
    python cleanup_test_data.py --apply      # Actually delete
"""

import asyncio
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from config import COLLECTIONS, get_settings

settings = get_settings()

async def get_database():
    client = AsyncIOMotorClient(settings.mongodb_url)
    return client[settings.database_name]

async def preview_counts(db):
    """Show current document counts."""
    collections = [
        "product_pieces", "import_batches", "customers",
        "registration_requests", "registered_products", "enquiries",
        "customer_feedbacks", "otp_sessions",
        "warranty_rules", "support_contacts", "catalogue_settings",
        "app_settings", "admin_users"
    ]
    
    print("\n=== CURRENT DATABASE COUNTS ===")
    for coll_name in collections:
        count = await db[coll_name].count_documents({})
        status = "KEEP" if coll_name in ["warranty_rules", "support_contacts", "catalogue_settings", "app_settings", "admin_users"] else "DELETE"
        print(f"  {coll_name:30s} : {count:6d}  [{status}]")
    
    # GridFS files
    try:
        gridfs_files = await db["catalogue_files.files"].count_documents({})
        gridfs_chunks = await db["catalogue_files.chunks"].count_documents({})
        print(f"  {'catalogue_files.files':30s} : {gridfs_files:6d}  [KEEP]")
        print(f"  {'catalogue_files.chunks':30s} : {gridfs_chunks:6d}  [KEEP]")
    except Exception:
        pass

async def cleanup_database(db, apply: bool = False):
    """Delete test data in correct order."""
    
    if not apply:
        print("\n=== PREVIEW MODE - No changes will be made ===")
        print("Run with --apply to execute deletion\n")
        return
    
    print("\n=== EXECUTING DELETION ===\n")
    
    # LEVEL 1: Leaf collections (no dependencies on other deletable collections)
    print("Level 1: Deleting leaf collections...")
    
    # customer_feedbacks - delete ALL (all customers are test)
    result = await db[COLLECTIONS["customer_feedbacks"]].delete_many({})
    print(f"  customer_feedbacks: deleted {result.deleted_count}")
    
    # enquiries - delete ALL
    result = await db[COLLECTIONS["enquiries"]].delete_many({})
    print(f"  enquiries: deleted {result.deleted_count}")
    
    # registered_products - delete ALL
    result = await db[COLLECTIONS["registered_products"]].delete_many({})
    print(f"  registered_products: deleted {result.deleted_count}")
    
    # registration_requests - delete ALL
    result = await db[COLLECTIONS["registration_requests"]].delete_many({})
    print(f"  registration_requests: deleted {result.deleted_count}")
    
    # LEVEL 2: Customers
    print("\nLevel 2: Deleting customers...")
    result = await db[COLLECTIONS["customers"]].delete_many({})
    print(f"  customers: deleted {result.deleted_count}")
    
    # LEVEL 3: Master product data
    print("\nLevel 3: Deleting master product data...")
    
    # product_pieces - delete ALL
    result = await db[COLLECTIONS["product_pieces"]].delete_many({})
    print(f"  product_pieces: deleted {result.deleted_count}")
    
    # import_batches - delete ALL
    result = await db[COLLECTIONS["import_batches"]].delete_many({})
    print(f"  import_batches: deleted {result.deleted_count}")
    
    # LEVEL 4: Auth temp
    print("\nLevel 4: Deleting auth temp data...")
    result = await db[COLLECTIONS["otp_sessions"]].delete_many({})
    print(f"  otp_sessions: deleted {result.deleted_count}")
    
    print("\n=== DELETION COMPLETE ===")

async def verify_cleanup(db):
    """Verify cleanup results."""
    print("\n=== VERIFICATION ===")
    
    # Should be zero
    zero_collections = [
        "product_pieces", "import_batches", "customers",
        "registration_requests", "registered_products", "enquiries",
        "customer_feedbacks", "otp_sessions"
    ]
    
    all_zero = True
    for coll_name in zero_collections:
        count = await db[coll_name].count_documents({})
        status = "OK" if count == 0 else "NOT EMPTY"
        if count != 0:
            all_zero = False
        print(f"  {coll_name:30s} : {count:6d}  [{status}]")
    
    # Should be preserved
    print("\nPreserved collections:")
    for coll_name in ["warranty_rules", "support_contacts", "catalogue_settings", "app_settings", "admin_users"]:
        count = await db[coll_name].count_documents({})
        print(f"  {coll_name:30s} : {count:6d}  [PRESERVED]")
    
    # GridFS
    try:
        gridfs_files = await db["catalogue_files.files"].count_documents({})
        gridfs_chunks = await db["catalogue_files.chunks"].count_documents({})
        print(f"  {'catalogue_files.files':30s} : {gridfs_files:6d}  [PRESERVED]")
        print(f"  {'catalogue_files.chunks':30s} : {gridfs_chunks:6d}  [PRESERVED]")
    except Exception:
        pass
    
    if all_zero:
        print("\n[SUCCESS] Cleanup successful - all test data removed")
    else:
        print("\n[WARNING] Some collections still have data")

async def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("--preview", "--apply"):
        print("Usage: python cleanup_test_data.py [--preview|--apply]")
        sys.exit(1)
    
    apply = sys.argv[1] == "--apply"
    
    db = await get_database()
    
    await preview_counts(db)
    
    if apply:
        confirm = input("\n[WARNING] This will DELETE all test data. Type 'YES' to confirm: ")
        if confirm != "YES":
            print("Cancelled.")
            return
    
    await cleanup_database(db, apply=apply)
    await verify_cleanup(db)

if __name__ == "__main__":
    asyncio.run(main())