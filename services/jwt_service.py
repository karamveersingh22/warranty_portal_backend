"""
JWT token generation and verification service.
"""

from datetime import datetime, timedelta
from jose import JWTError, jwt
from config import get_settings
import logging
from typing import Optional

logger = logging.getLogger(__name__)
settings = get_settings()


def create_token(email: str, role: str) -> str:
    """Create a 24-hour JWT token."""
    issued_at = datetime.utcnow()
    expires_at = issued_at + timedelta(hours=settings.jwt_expiry_hours)
    normalized_email = email.lower().strip()
    payload = {
        "sub": normalized_email,
        "email": normalized_email,
        "role": role,
        "exp": expires_at,
        "iat": issued_at,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def verify_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token."""
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        if not payload.get("email") or payload.get("role") not in {"customer", "admin"}:
            return None
        return payload
    except JWTError as e:
        logger.warning(f"JWT validation failed: {str(e)}")
        return None
