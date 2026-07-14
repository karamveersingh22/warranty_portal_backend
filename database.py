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
OTP_EMAIL_ROLE_INDEX = "email_1_role_1"


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

    await _reconcile_otp_email_role_index()

    failures = []
    for collection_name, indexes in COLLECTION_INDEXES.items():
        if not indexes:
            continue
        try:
            await db[collection_name].create_indexes(indexes)
        except Exception as exc:
            failures.append(collection_name)
            logger.warning("Index creation warning for %s: %s", collection_name, str(exc))

    if failures:
        logger.warning("Index creation completed with warnings for: %s", ", ".join(failures))
    else:
        logger.info("MongoDB indexes created")


async def _reconcile_otp_email_role_index():
    """Upgrade the legacy non-unique OTP email/role index safely.

    Older deployments created ``email_1_role_1`` without ``unique=True``.
    MongoDB cannot change that option in place. OTP sessions are temporary, so
    for duplicate keys we retain the newest session, remove the older copies,
    and then drop the stale index. The normal model-driven index pass recreates
    it with the required unique option.
    """
    collection = db["otp_sessions"]
    try:
        indexes = await collection.index_information()
        existing = indexes.get(OTP_EMAIL_ROLE_INDEX)
        if not existing or existing.get("unique") is True:
            return

        logger.info("Upgrading legacy non-unique OTP email/role index")
        duplicate_groups = await collection.aggregate([
            {"$sort": {"updated_at": -1, "created_at": -1, "_id": -1}},
            {
                "$group": {
                    "_id": {"email": "$email", "role": "$role"},
                    "ids": {"$push": "$_id"},
                    "count": {"$sum": 1},
                }
            },
            {"$match": {"count": {"$gt": 1}}},
        ]).to_list(None)

        duplicate_ids = [
            duplicate_id
            for group in duplicate_groups
            for duplicate_id in group.get("ids", [])[1:]
        ]
        if duplicate_ids:
            result = await collection.delete_many({"_id": {"$in": duplicate_ids}})
            logger.info("Removed %s stale duplicate OTP session(s)", result.deleted_count)

        await collection.drop_index(OTP_EMAIL_ROLE_INDEX)
        logger.info("Dropped legacy OTP index; it will be recreated as unique")
    except Exception as exc:
        # Do not prevent startup. The per-collection index pass below will log
        # any remaining conflict while allowing unrelated indexes to proceed.
        logger.warning("Could not reconcile legacy OTP index: %s", str(exc))


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
