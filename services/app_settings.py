"""Admin-configurable application settings stored as a single document."""

from config import COLLECTIONS

SETTINGS_ID = "config"
DEFAULT_FLAG_DAYS = 60
MIN_FLAG_DAYS = 1
MAX_FLAG_DAYS = 3650


async def get_flag_days(db) -> int:
    """Return the configured 'old product' flag threshold in days."""
    doc = await db[COLLECTIONS["app_settings"]].find_one({"_id": SETTINGS_ID})
    if doc and isinstance(doc.get("old_product_flag_days"), int):
        return doc["old_product_flag_days"]
    return DEFAULT_FLAG_DAYS


async def set_flag_days(db, days: int) -> int:
    """Persist the 'old product' flag threshold (clamped to a sane range)."""
    days = max(MIN_FLAG_DAYS, min(int(days), MAX_FLAG_DAYS))
    await db[COLLECTIONS["app_settings"]].update_one(
        {"_id": SETTINGS_ID},
        {"$set": {"old_product_flag_days": days}},
        upsert=True,
    )
    return days
