"""
Authentication routes: /api/auth
- POST /send-otp
- POST /verify-otp
- GET /me
"""

from datetime import datetime
import logging

from fastapi import APIRouter, Depends, HTTPException, status

from config import COLLECTIONS, get_settings
from database import get_database
from middleware.auth_guard import get_current_user
from schemas import OTPRequest, OTPVerifyRequest, TokenResponse, UserResponse
from services.jwt_service import create_token
from services.otp_service import generate_otp, get_otp_expiry, hash_otp, send_otp_email, verify_otp_hash

logger = logging.getLogger(__name__)
settings = get_settings()
router = APIRouter(prefix="/api/auth", tags=["auth"])


def normalize_email(email: str) -> str:
    return email.lower().strip()


def resolve_role_from_email(email: str) -> str:
    return "admin" if normalize_email(email) in settings.admin_emails else "customer"


async def get_user_for_role(db, email: str, role: str) -> dict:
    if role == "admin":
        normalized_email = normalize_email(email)
        if normalized_email in settings.admin_emails:
            return {
                "email": normalized_email,
                "role": "admin",
                "name": "Admin",
            }

        return None
    return await db[COLLECTIONS["customers"]].find_one({"email": email})


@router.post("/send-otp")
async def send_otp(request: OTPRequest, db=Depends(get_database)):
    """Send a 6-digit OTP and infer customer/admin role from the email."""
    email = normalize_email(request.email)
    role = resolve_role_from_email(email)
    now = datetime.utcnow()

    if role == "admin":
        admin_user = await get_user_for_role(db, email, "admin")
        if not admin_user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This email is not allowed to login as admin",
            )

    otp_collection = db[COLLECTIONS["otp_sessions"]]
    existing = await otp_collection.find_one({"email": email, "role": role})

    if existing and existing.get("expires_at") and existing["expires_at"] > now:
        if existing.get("resend_count", 0) >= settings.otp_max_resend:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many OTP requests. Please wait for the current OTP to expire.",
            )
        resend_count = existing.get("resend_count", 0) + 1
    else:
        resend_count = 1

    otp = generate_otp()
    if not await send_otp_email(email, otp):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to send OTP email",
        )

    expires_at = get_otp_expiry()
    await otp_collection.update_one(
        {"email": email, "role": role},
        {
            "$set": {
                "email": email,
                "role": role,
                "otp_hash": hash_otp(otp),
                "expires_at": expires_at,
                "resend_count": resend_count,
                "verified": False,
                "updated_at": now,
            },
            "$setOnInsert": {
                "created_at": now,
            },
            "$unset": {
                "otp": "",
            },
        },
        upsert=True,
    )

    return {
        "message": "OTP sent successfully",
        "email": email,
        "role": role,
        "expires_in_seconds": settings.otp_expiry_minutes * 60,
    }


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(request: OTPVerifyRequest, db=Depends(get_database)):
    """Verify OTP and issue a JWT token with role inferred from email."""
    email = normalize_email(request.email)
    role = resolve_role_from_email(email)
    now = datetime.utcnow()

    otp_collection = db[COLLECTIONS["otp_sessions"]]
    otp_record = await otp_collection.find_one({"email": email, "role": role})

    if not otp_record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP not found. Request a new OTP.")

    if otp_record.get("verified"):
        await otp_collection.delete_one({"_id": otp_record["_id"]})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP already used. Request a new OTP.")

    if not otp_record.get("expires_at") or otp_record["expires_at"] <= now:
        await otp_collection.delete_one({"_id": otp_record["_id"]})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="OTP expired. Request a new OTP.")

    otp_hash = otp_record.get("otp_hash")
    if not otp_hash or not verify_otp_hash(request.otp, otp_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid OTP")

    user_doc = await get_user_for_role(db, email, role)
    if role == "admin" and not user_doc:
        await otp_collection.delete_one({"_id": otp_record["_id"]})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized as admin")

    await otp_collection.delete_one({"_id": otp_record["_id"]})

    token = create_token(email, role)
    return TokenResponse(
        access_token=token,
        expires_in=settings.jwt_expiry_hours * 60 * 60,
        user={
            "email": email,
            "role": role,
            "name": user_doc.get("name") if user_doc else None,
        },
    )


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user), db=Depends(get_database)):
    """Return current authenticated user information."""
    email = normalize_email(current_user["email"])
    role = current_user["role"]
    user_doc = await get_user_for_role(db, email, role)

    if role == "admin" and not user_doc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access revoked")

    return UserResponse(
        email=email,
        role=role,
        name=user_doc.get("name") if user_doc else None,
    )
