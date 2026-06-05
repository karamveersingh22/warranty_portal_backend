"""
MongoDB connection handler using Motor.

Provides dependency injection for database access and creates collection indexes
declared by the MongoDB document models.
"""

import logging

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from models import COLLECTION_INDEXES

logger = logging.getLogger(__name__)

mongodb_client: AsyncIOMotorClient = None
db: AsyncIOMotorDatabase = None


async def connect_to_mongo(mongodb_url: str, db_name: str):
    """Initialize MongoDB connection."""
    global mongodb_client, db

    logger.info("Connecting to MongoDB...")
    mongodb_client = AsyncIOMotorClient(
        mongodb_url,
        serverSelectionTimeoutMS=15000,
        connectTimeoutMS=15000,
    )
    db = mongodb_client[db_name]

    await db.command("ping")
    logger.info("MongoDB connected")

    await create_indexes()


async def create_indexes():
    """Create MongoDB indexes from model declarations."""
    global db

    try:
        for collection_name, indexes in COLLECTION_INDEXES.items():
            if indexes:
                await db[collection_name].create_indexes(indexes)

        logger.info("MongoDB indexes created")
    except Exception as e:
        logger.warning("Index creation warning: %s", str(e))


async def close_mongo_connection():
    """Close MongoDB connection."""
    global mongodb_client

    if mongodb_client:
        mongodb_client.close()
        logger.info("MongoDB connection closed")


async def get_database() -> AsyncIOMotorDatabase:
    """Dependency for getting database instance."""
    return db


def get_db_sync() -> AsyncIOMotorDatabase:
    """Synchronous wrapper for getting database."""
    return db
