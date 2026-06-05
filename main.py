"""
Warranty Portal - Backend API
FastAPI + Motor (async MongoDB) + Email OTP Auth

ARCHITECTURE:
- FastAPI for async REST APIs
- Motor for async MongoDB connection
- Email OTP via Gmail SMTP (no phone OTP)
- JWT tokens with role-based access (customer/admin)
- Strict input validation using Pydantic
- CORS enabled for frontend development and configured production frontend URL
"""

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import get_settings
from database import close_mongo_connection, connect_to_mongo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Warranty Portal API starting...")

    await connect_to_mongo(settings.mongodb_url, settings.database_name)

    yield

    await close_mongo_connection()
    logger.info("Warranty Portal API shutting down...")


app = FastAPI(
    title="Warranty Portal API",
    description="Backend for warranty registration, tracking, and enquiry management",
    version="1.0.0",
    lifespan=lifespan,
)


allowed_origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
frontend_url = settings.frontend_url.rstrip("/") if settings.frontend_url else ""
if frontend_url and frontend_url not in allowed_origins:
    allowed_origins.append(frontend_url)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


from routes import admin, auth, customer, enquiry, pieces, rules, upload, warranty

app.include_router(admin.router)
app.include_router(auth.router)
app.include_router(customer.router)
app.include_router(pieces.router)
app.include_router(warranty.router)
app.include_router(enquiry.router)
app.include_router(rules.router)
app.include_router(upload.router)


@app.get("/health")
async def health_check():
    """Health check endpoint with no authentication."""
    return {
        "status": "ok",
        "service": "warranty-portal-api",
        "version": "1.0.0",
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Warranty Portal API",
        "docs": "/docs",
        "health": "/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
