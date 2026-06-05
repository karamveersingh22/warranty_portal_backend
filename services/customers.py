"""Customer account helpers shared by customer-owned workflows."""

from config import COLLECTIONS

PROFILE_REQUIRED_MESSAGE = "Complete your profile before proceeding further"


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


async def get_customer_by_email(db, email: str) -> dict | None:
    return await db[COLLECTIONS["customers"]].find_one({"email": normalize_email(email)})


def has_complete_profile(customer: dict | None) -> bool:
    if not customer or not customer.get("profile_complete"):
        return False

    required_fields = ("name", "phone", "address", "city")
    return all(str(customer.get(field) or "").strip() for field in required_fields)
