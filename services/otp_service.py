"""
OTP service for generating, hashing, and sending email OTPs.
"""

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta

import httpx

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def generate_otp() -> str:
    """Generate a cryptographically strong 6-digit OTP."""
    return f"{secrets.randbelow(1_000_000):06d}"


def hash_otp(otp: str) -> str:
    """Hash OTP before storing it in MongoDB."""
    return hmac.new(
        settings.jwt_secret.encode("utf-8"),
        otp.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_otp_hash(otp: str, otp_hash: str) -> bool:
    """Compare an OTP with its stored hash."""
    return hmac.compare_digest(hash_otp(otp), otp_hash)


def get_otp_expiry() -> datetime:
    """Get OTP expiry time."""
    return datetime.utcnow() + timedelta(minutes=settings.otp_expiry_minutes)


async def send_otp_email(to_email: str, otp: str) -> bool:
    """Send OTP via Brevo Email API. In development mode, log the OTP locally."""
    if settings.environment.lower() in ("development", "local", "dev"):
        logger.info("DEV MODE - OTP for %s: %s", to_email, otp)
        print(f"\n{'=' * 50}")
        print(f"  DEV MODE - OTP for {to_email}: {otp}")
        print(f"{'=' * 50}\n")
        return True

    if not settings.brevo_api_key or not settings.brevo_sender_email:
        logger.error("Brevo API credentials are not configured")
        return False

    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": settings.brevo_api_key,
        "content-type": "application/json",
    }
    
    text = (
        f"Your Warranty Portal OTP is: {otp}\n\n"
        f"This OTP expires in {settings.otp_expiry_minutes} minutes."
    )
    html = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #111827;">
        <div style="max-width: 560px; margin: 0 auto; padding: 24px;">
          <h2 style="margin-bottom: 12px;">Warranty Portal</h2>
          <p>Your one-time password is:</p>
          <p style="font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #2563eb;">{otp}</p>
          <p style="color: #4b5563;">This OTP expires in {settings.otp_expiry_minutes} minutes.</p>
          <p style="color: #6b7280; font-size: 12px; margin-top: 24px;">
            If you did not request this OTP, you can ignore this email.
          </p>
        </div>
      </body>
    </html>
    """
    
    payload = {
        "sender": {
            "name": settings.brevo_sender_name,
            "email": settings.brevo_sender_email
        },
        "to": [{"email": to_email}],
        "subject": "Warranty Portal - Your OTP",
        "htmlContent": html,
        "textContent": text
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=payload, timeout=15.0)
            
        if response.status_code in (200, 201, 202):
            logger.info("OTP sent to %s via Brevo API", to_email)
            return True
        else:
            logger.error(
                "Brevo API error for %s. Status: %s, Response: %s", 
                to_email, response.status_code, response.text
            )
            return False
            
    except Exception as exc:
        logger.error("Failed to send OTP to %s via Brevo API: %s", to_email, exc)
        return False
