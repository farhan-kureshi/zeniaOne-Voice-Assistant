"""
Zenaipex AI — Database Index Initialization Script.

Run ONCE on a fresh database (or safely re-run — MongoDB ignores duplicate indexes).

Usage:
    cd d:\\Sarvam-Voice-Agent-main\\zenaipex
    python scripts/init_db.py

Requires: MONGODB_URI in .env
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings
from core.database import connect_db, create_all_indexes, disconnect_db


async def main():
    print("=" * 60)
    print("Zenaipex AI — Database Initialization")
    print(f"  Database: {settings.mongodb_db_name}")
    print(f"  URI: {settings.mongodb_uri[:40]}..." if settings.mongodb_uri else "  URI: NOT SET")
    print("=" * 60)

    if not settings.mongodb_uri:
        print("❌ MONGODB_URI not set in .env")
        sys.exit(1)

    connected = await connect_db()
    if not connected:
        print("❌ Failed to connect to MongoDB")
        sys.exit(1)

    print("📋 Creating indexes...")
    try:
        await create_all_indexes()
        print("✅ All indexes created successfully")
    except Exception as exc:
        print(f"❌ Index creation failed: {exc}")
        sys.exit(1)
    finally:
        await disconnect_db()

    print("\n✅ Database initialization complete!")
    print("\nNext step: Run the RK Hospital migration:")
    print("   python scripts/migrate_rk_hospital.py --dry-run")


if __name__ == "__main__":
    asyncio.run(main())
