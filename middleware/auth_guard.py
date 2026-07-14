"""
Authentication middleware for route protection.
Verifies JWT tokens and injects user info into requests.
"""

# pyrefly: ignore [missing-import]
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import HTTPException, Depends
from typing import Optional
from services.jwt_service import verify_token
from database import get_database
import logging

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)


async def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> dict:
    """
    Dependency for protected routes.
    Extracts and verifies JWT token from Authorization header.
    """
    if not credentials:
        raise HTTPException(status_code=401, detail="No authorization header")

    if credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Invalid authorization scheme")

    token = credentials.credentials
    if token.lower().startswith("bearer "):
        token = token[7:]

    payload = verify_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    return payload


async def get_current_customer_identity(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency for customer-only routes.
    """
    if current_user.get("role") != "customer":
        raise HTTPException(status_code=403, detail="Customer access required")
    return current_user


async def get_current_customer(
    current_user: dict = Depends(get_current_customer_identity),
    db=Depends(get_database),
) -> dict:
    """Customer guard that also enforces mandatory onboarding-term acceptance."""
    email = (current_user.get("email") or "").lower().strip()
    customer = await db["customers"].find_one({"email": email})
    if customer and customer.get("terms_required") and not customer.get("onboarding_terms_accepted"):
        raise HTTPException(
            status_code=403,
            detail="You must accept all terms and conditions before continuing.",
        )
    return current_user


async def get_current_admin(current_user: dict = Depends(get_current_user)) -> dict:
    """
    Dependency for admin-only routes.
    """
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user
