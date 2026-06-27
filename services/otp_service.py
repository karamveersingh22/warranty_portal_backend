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
    
    expiry_minutes = settings.otp_expiry_minutes
    text = (
        "Safrina Mattress - Warranty Portal\n\n"
        "Here is your one-time verification code to sign in to the Safrina Mattress "
        f"Warranty Portal:\n\n"
        f"    {otp}\n\n"
        f"This code is valid for {expiry_minutes} minutes. Please do not share it with anyone.\n\n"
        "If you did not request this code, you can safely ignore this email.\n\n"
        "- Team Safrina Mattress"
    )
    html = f"""
    <html>
      <body style="margin:0; padding:0; background-color:#f3f6fb;">
        <div style="font-family: Arial, Helvetica, sans-serif; color:#1f2533; background-color:#f3f6fb; padding:32px 16px;">
          <div style="max-width:520px; margin:0 auto; background-color:#ffffff; border:1px solid #dce3ee; border-radius:14px; overflow:hidden;">
            <div style="background-color:#1d3557; padding:24px 28px;">
              <div style="font-size:20px; font-weight:700; color:#ffffff; letter-spacing:0.2px;">Safrina Mattress</div>
              <div style="font-size:11px; font-weight:600; letter-spacing:2px; text-transform:uppercase; color:#e85680; margin-top:4px;">Pamper yourself</div>
            </div>
            <div style="padding:28px;">
              <p style="font-size:15px; margin:0 0 6px; color:#1f2533;">Hi,</p>
              <p style="font-size:15px; line-height:1.6; margin:0 0 20px; color:#4a5468;">
                Here is your one-time verification code to sign in to the
                <strong style="color:#1d3557;">Safrina Mattress Warranty Portal</strong>.
              </p>
              <div style="text-align:center; margin:24px 0;">
                <div style="display:inline-block; background-color:#f3f6fb; border:1px solid #dce3ee; border-radius:12px; padding:16px 28px;">
                  <span style="font-size:34px; font-weight:700; letter-spacing:10px; color:#1d3557;">{otp}</span>
                </div>
              </div>
              <p style="font-size:14px; line-height:1.6; margin:0 0 6px; color:#4a5468;">
                This code is valid for <strong>{expiry_minutes} minutes</strong>. For your security, please do not share it with anyone.
              </p>
              <p style="font-size:13px; line-height:1.6; color:#677288; margin:18px 0 0;">
                If you did not request this code, you can safely ignore this email.
              </p>
            </div>
            <div style="border-top:1px solid #eaeff7; padding:18px 28px; background-color:#fbfcfe;">
              <p style="font-size:12px; color:#677288; margin:0;">
                This is an automated message from the Safrina Mattress Warranty Portal. Please do not reply.
              </p>
              <p style="font-size:12px; color:#94a1b8; margin:6px 0 0;">
                &copy; {datetime.utcnow().year} Safrina Mattress. All rights reserved.
              </p>
            </div>
          </div>
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
        "subject": f"{otp} is your Safrina Mattress verification code",
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
