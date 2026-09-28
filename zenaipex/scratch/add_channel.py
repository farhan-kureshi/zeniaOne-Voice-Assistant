import asyncio
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.getcwd())
from core.database import col_channels, connect_db

async def main():
    await connect_db()
    
    # Check if this number already exists
    exists = await col_channels().find_one({"phone_number": "+19144443927"})
    if exists:
        print("Channel already exists in DB!")
        return
        
    doc = {
        "company_id": "6a990b403e9b17bef89acf87",
        "agent_id": "6a990b403e9b17bef89acf8b", # ZeniaAI Assistant
        "name": "US Voice Support (+1 914-444-3927)",
        "type": "twilio_voice",
        "phone_number": "+19144443927",
        "is_active": True,
        "config": {
            "allowed_domains": ["www.zeniaone.com"]
        },
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    
    result = await col_channels().insert_one(doc)
    print(f"Added channel with ID: {result.inserted_id}")

if __name__ == "__main__":
    asyncio.run(main())
