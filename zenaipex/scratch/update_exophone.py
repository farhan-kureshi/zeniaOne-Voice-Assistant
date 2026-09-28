import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from core.database import col_channels, connect_db

async def main():
    await connect_db()
    result = await col_channels().update_one(
        {"type": "twilio_voice", "company_id": "6a990b403e9b17bef89acf87"},
        {"$set": {
            "phone_number": "08047285182",
            "name": "India Voice Support (Exotel)",
            "type": "exotel_voice"
        }}
    )
    print(f"Modified {result.modified_count} channels to Exotel.")

if __name__ == "__main__":
    asyncio.run(main())
