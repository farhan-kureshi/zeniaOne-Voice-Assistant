"""
Zenaipex AI — MongoDB async connection pool.

Uses Motor (async PyMongo driver). All collections are accessed via
this module. Every query MUST include company_id for tenant isolation.
"""
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, IndexModel
from typing import Optional
import logging

from zenaipex.core.config import settings

logger = logging.getLogger(__name__)

# ── Connection Globals ────────────────────────────────────────────────────────

_client: Optional[AsyncIOMotorClient] = None
_db: Optional[AsyncIOMotorDatabase] = None
_db_mode: str = "disconnected"  # "mongomock" | "mongodb" | "disconnected"


async def connect_db() -> bool:
    """
    Initialize the MongoDB async connection pool.
    Called once during FastAPI startup (lifespan).
    """
    global _client, _db, _db_mode

    if not settings.mongodb_uri:
        logger.error("❌ MONGODB_URI not set — database unavailable. System cannot continue without a real MongoDB instance.")
        raise RuntimeError("MONGODB_URI environment variable is required.")

    try:
        logger.info("Connecting to MongoDB...")
        _client = AsyncIOMotorClient(
            settings.mongodb_uri,
            serverSelectionTimeoutMS=15_000,
            connectTimeoutMS=15_000,
            socketTimeoutMS=20_000,
            retryWrites=True,
            w="majority",
            maxPoolSize=50,
            minPoolSize=5,
            tz_aware=True,
        )
        # Verify connectivity
        await _client.admin.command("ping")
        _db = _client[settings.mongodb_db_name]
        _db_mode = "mongodb"
        logger.info(f"✅ MongoDB connected → db: {settings.mongodb_db_name} [PERSISTENT]")
        return True
    except Exception as exc:
        logger.error(f"❌ MongoDB connection failed: {exc}")
        raise RuntimeError(f"MongoDB connection failed: {exc}")


async def disconnect_db():
    """Close the MongoDB connection pool. Called on FastAPI shutdown."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed")


def get_db() -> AsyncIOMotorDatabase:
    """Return the active database handle. Raises if not connected."""
    if _db is None:
        raise RuntimeError("Database not connected. Call connect_db() first.")
    return _db


def get_db_mode() -> dict:
    """Return current database mode for health checks and UI banners."""
    return {
        "db_mode": _db_mode,
        "persistent": _db_mode == "mongodb",
        "db_name": settings.mongodb_db_name,
    }


# ── Collection Accessors ──────────────────────────────────────────────────────
# All collections accessed via typed functions so we never typo a name.

def col_companies():       return get_db()["companies"]
def col_users():           return get_db()["users"]
def col_team_members():    return get_db()["team_members"]
def col_subscriptions():   return get_db()["subscriptions"]
def col_agents():          return get_db()["agents"]
def col_knowledge_bases(): return get_db()["knowledge_bases"]
def col_documents():       return get_db()["documents"]
def col_channels():        return get_db()["channels"]
def col_conversations():   return get_db()["conversations"]
def col_messages():        return get_db()["messages"]
def col_usage_records():   return get_db()["usage_records"]
def col_scheduled_calls(): return get_db()["scheduled_calls"]
def col_timing_metrics():  return get_db()["timing_metrics"]
def col_activity_logs():   return get_db()["activity_logs"]
def col_leads():           return get_db()["leads"]
def col_sales_calls():     return get_db()["sales_calls"]
def col_ai_providers():    return get_db()["ai_providers"]
def col_platform_settings(): return get_db()["platform_settings"]
def col_llm_requests():    return get_db()["llm_requests"]

# ── Index Initialization ──────────────────────────────────────────────────────

async def create_all_indexes():
    """
    Create all MongoDB indexes required for Zenaipex.
    Safe to call on every startup — MongoDB ignores existing identical indexes.

    MULTI-TENANT DESIGN: Every collection that holds company data has a
    compound index on (company_id, <key field>) so queries are always
    fast and correctly scoped.
    """
    db = get_db()

    # companies
    await db["companies"].create_indexes([
        IndexModel([("slug", ASCENDING)], unique=True),
        IndexModel([("created_at", DESCENDING)]),
        IndexModel([("plan", ASCENDING)]),
    ])

    # users (platform users, cross-company)
    await db["users"].create_indexes([
        IndexModel([("email", ASCENDING)], unique=True),
        IndexModel([("created_at", DESCENDING)]),
        IndexModel([("is_verified", ASCENDING)]),
    ])

    # team_members (user↔company relationship)
    await db["team_members"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("user_id", ASCENDING)], unique=True),
        IndexModel([("company_id", ASCENDING), ("role", ASCENDING)]),
        IndexModel([("user_id", ASCENDING)]),
    ])

    # subscriptions
    await db["subscriptions"].create_indexes([
        IndexModel([("company_id", ASCENDING)], unique=True),
        IndexModel([("plan", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("trial_ends_at", ASCENDING)]),
    ])

    # agents
    await db["agents"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("slug", ASCENDING)], unique=True),
        IndexModel([("company_id", ASCENDING), ("is_active", ASCENDING)]),
        IndexModel([("company_id", ASCENDING)]),
    ])

    # knowledge_bases
    await db["knowledge_bases"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("name", ASCENDING)]),
        IndexModel([("company_id", ASCENDING)]),
        IndexModel([("pinecone_namespace", ASCENDING)], unique=True, sparse=True),
    ])

    # documents
    await db["documents"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("knowledge_base_id", ASCENDING)]),
        IndexModel([("company_id", ASCENDING), ("status", ASCENDING)]),
        IndexModel([("content_hash", ASCENDING)]),
    ])

    # channels
    await db["channels"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("type", ASCENDING)]),
        IndexModel([("phone_number", ASCENDING)], sparse=True),
        IndexModel([("company_id", ASCENDING), ("agent_id", ASCENDING)]),
    ])

    # conversations
    await db["conversations"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("started_at", DESCENDING)]),
        IndexModel([("company_id", ASCENDING), ("status", ASCENDING)]),
        IndexModel([("company_id", ASCENDING), ("caller_phone", ASCENDING)]),
        IndexModel([("call_sid", ASCENDING)], sparse=True),
        IndexModel([("agent_id", ASCENDING)]),
    ])

    # messages (transcripts)
    await db["messages"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("conversation_id", ASCENDING),
                    ("timestamp", ASCENDING)]),
        IndexModel([("conversation_id", ASCENDING)]),
    ])

    # usage_records
    await db["usage_records"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("month", ASCENDING)], unique=True),
        IndexModel([("company_id", ASCENDING)]),
    ])

    # scheduled_calls (MIGRATED FROM LEGACY — added company_id)
    await db["scheduled_calls"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("status", ASCENDING)]),
        IndexModel([("company_id", ASCENDING), ("scheduled_at", ASCENDING)]),
        IndexModel([("status", ASCENDING), ("scheduled_at", ASCENDING)]),
        IndexModel([("next_retry_at", ASCENDING)], sparse=True),
        IndexModel([("phone_number", ASCENDING)]),
    ])

    # timing_metrics
    await db["timing_metrics"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("timestamp", DESCENDING)]),
        IndexModel([("call_sid", ASCENDING)], sparse=True),
    ])

    # activity_logs
    await db["activity_logs"].create_indexes([
        IndexModel([("created_at", DESCENDING)]),
        IndexModel([("actor_email", ASCENDING)]),
        IndexModel([("action", ASCENDING)]),
    ])

    # ai_providers
    await db["ai_providers"].create_indexes([
        IndexModel([("provider", ASCENDING)], unique=True),
        IndexModel([("enabled", DESCENDING), ("priority", ASCENDING)]),
    ])

    # platform_settings
    await db["platform_settings"].create_indexes([
        IndexModel([("type", ASCENDING)], unique=True),
    ])

    # llm_requests
    await db["llm_requests"].create_indexes([
        IndexModel([("company_id", ASCENDING), ("timestamp", DESCENDING)]),
        IndexModel([("provider", ASCENDING), ("model", ASCENDING)]),
        IndexModel([("timestamp", DESCENDING)]),
    ])

    logger.info("✅ All MongoDB indexes created/verified")
