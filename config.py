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

    # Email OTP (Gmail SMTP)
    gmail_user: str = ""
    gmail_app_password: str = ""
    otp_expiry_minutes: int = 10
    otp_max_resend: int = 3

    # Admin
    admin_email: str = "admin@warranty.local"

    # Frontend URL
    frontend_url: str = "http://localhost:5173"

    # Environment
    environment: str = "development"
    debug: bool = True

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
    "registered_products": "registered_products",
    "warranty_rules": "warranty_rules",
    "enquiries": "enquiries",
    "import_batches": "import_batches",
}
