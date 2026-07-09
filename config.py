"""
Configuration and environment loading for backend.
Uses python-dotenv to load from .env files.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    """Backend settings loaded from environment variables"""

    # MongoDB
    mongodb_url: str = "mongodb://localhost:27017"
    database_name: str = "warranty_portal"

    # JWT Authentication
    jwt_secret: str = "your-super-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    # Email OTP (Brevo API)
    brevo_api_key: str = ""
    brevo_sender_email: str = ""
    brevo_sender_name: str = "Warranty Portal"
    otp_expiry_minutes: int = 10
    otp_max_resend: int = 3

    # Admin (single email or comma-separated list of admin emails)
    admin_email: str = "admin@warranty.local"

    # Frontend URL
    frontend_url: str = "http://localhost:5173"

    # Environment
    environment: str = "development"
    debug: bool = True

    @property
    def admin_emails(self) -> list[str]:
        """Parse `admin_email` into a normalized list of admin emails.

        Supports a single value or a comma-separated list, e.g.
        `ADMIN_EMAIL=client@gmail.com,owner@gmail.com`.
        """
        return [
            email.lower().strip()
            for email in self.admin_email.split(",")
            if email.strip()
        ]

    @property
    def frontend_urls(self) -> list[str]:
        """Parse `frontend_url` into a list of allowed CORS origins.

        Supports a single value or a comma-separated list, e.g.
        `FRONTEND_URL=https://safrinamattress.com,https://www.safrinamattress.com`.
        Trailing slashes are stripped so origins match exactly.
        """
        return [
            url.strip().rstrip("/")
            for url in self.frontend_url.split(",")
            if url.strip()
        ]

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """Get settings singleton"""
    return Settings()


# MongoDB Collection Names (constants used throughout the app)
COLLECTIONS = {
    "customers": "customers",
    "admin_users": "admin_users",
    "otp_sessions": "otp_sessions",
    "product_pieces": "product_pieces",
    "registration_requests": "registration_requests",
    "registered_products": "registered_products",
    "warranty_rules": "warranty_rules",
    "enquiries": "enquiries",
    "import_batches": "import_batches",
    "app_settings": "app_settings",
    "support_contacts": "support_contacts",
}
