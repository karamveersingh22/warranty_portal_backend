"""Re-parse item_name into product_type / category / size for all existing product_pieces.

Updates in place (no re-upload needed), grouped by distinct item_name for efficiency.
Run with --apply to write changes; without it, only previews.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from config import get_settings
from services.dbf_parser import parse_item_name


async def main(apply: bool):
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.database_name]
    col = db["product_pieces"]

    names = await col.distinct("item_name")
    print(f"Distinct item_name values: {len(names)}")

    categories = set()
    updated_docs = 0
    for name in names:
        product_type, category, size = parse_item_name(name)
        categories.add(category)
        if apply:
            res = await col.update_many(
                {"item_name": name},
                {"$set": {
                    "product_type": product_type,
                    "category": category,
                    "size": size,
                }},
            )
            updated_docs += res.modified_count

    print(f"\nResulting distinct categories: {len(categories)}")
    print("=" * 50)
    for c in sorted(categories):
        print(repr(c))

    if apply:
        print(f"\nAPPLIED. Documents updated: {updated_docs}")
    else:
        print("\nDRY RUN. Re-run with --apply to write these changes.")

    client.close()


if __name__ == "__main__":
    asyncio.run(main(apply="--apply" in sys.argv))
