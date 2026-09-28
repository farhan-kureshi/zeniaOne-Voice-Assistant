import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())
from core.database import col_channels, connect_db

async def main():
    await connect_db()
    docs = await col_channels().find({}).to_list(100)
    print("Found channels:")
    for d in docs:
        print(f"Type: {d.get('type')}, Phone: {d.get('phone_number')}, Company ID: {d.get('company_id')}, IsActive: {d.get('is_active')}")

if __name__ == "__main__":
    asyncio.run(main())
