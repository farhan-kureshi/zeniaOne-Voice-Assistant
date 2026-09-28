import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from bson import ObjectId
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv('zenaipex/.env')
uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
db_name = os.getenv('MONGODB_DB_NAME', 'zenaipex')

async def restore():
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    
    company_id = '6a990b403e9b17bef89acf87'
    channel_id = '6ab7c0adc39381e9f59801be'
    
    # 08:00 AM IST is 02:30 AM UTC
    t1 = datetime(2026, 9, 28, 2, 30, 31, 319000, tzinfo=timezone.utc)
    # 10:49 AM IST is 05:19 AM UTC
    t2 = datetime(2026, 9, 28, 5, 19, 39, 754000, tzinfo=timezone.utc)
    
    doc1 = {
        "_id": ObjectId("6ab9d147da83871238dd7007"),
        "company_id": company_id,
        "agent_id": "6a990b403e9b17bef89acf8b",
        "channel_id": channel_id,
        "caller_phone": "Farhan (Admin)",
        "caller_to": "08047285182",
        "direction": "outbound",
        "language": "en-IN",
        "status": "completed",
        "started_at": t1,
        "created_at": t1,
        "ended_at": t1 + timedelta(seconds=19),
        "duration_seconds": 19,
        "turn_count": 1,
        "is_pinned": False,
        "title": "New Chat"
    }
    
    doc2 = {
        "_id": ObjectId("6ab9f8ebb22bca99a954f529"),
        "company_id": company_id,
        "agent_id": "6a990b403e9b17bef89acf8b",
        "channel_id": channel_id,
        "caller_phone": "Farhan (Admin)",
        "caller_to": "08047285182",
        "direction": "outbound",
        "language": "en-IN",
        "status": "hung-up",
        "started_at": t2,
        "created_at": t2,
        "ended_at": t2 + timedelta(seconds=8),
        "duration_seconds": 8,
        "turn_count": 1,
        "is_pinned": False,
        "title": "New Chat"
    }
    
    try:
        await db.conversations.insert_many([doc1, doc2])
        print("Restored successfully")
    except Exception as e:
        print(f"Error restoring: {e}")

asyncio.run(restore())
