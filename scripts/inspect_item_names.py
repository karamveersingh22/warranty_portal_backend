"""Read-only: print distinct item_name + current parsed fields to understand the real format."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient
from config import get_settings


async def main():
    settings = get_settings()
    client = AsyncIOMotorClient(settings.mongodb_url)
    db = client[settings.database_name]

    total = await db["product_pieces"].count_documents({})
    print(f"Total product_pieces: {total}\n")

    # Distinct raw item names
    names = await db["product_pieces"].distinct("item_name")
    print(f"Distinct item_name count: {len(names)}")
    print("=" * 70)
    for n in sorted(names)[:60]:
        print(repr(n))
    print("=" * 70)

    # Show current parsed fields for a sample
    print("\nCurrent parsed fields (sample of 15):")
    cursor = db["product_pieces"].find(
        {}, {"item_name": 1, "product_type": 1, "category": 1, "size": 1, "_id": 0}
    ).limit(15)
    async for doc in cursor:
        print(doc)

    # Distinct categories currently stored
    cats = await db["product_pieces"].distinct("category")
    print(f"\nDistinct stored categories ({len(cats)}):")
    for c in sorted(cats):
        print(repr(c))

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
