import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from dotenv import load_dotenv

load_dotenv('zenaipex/.env')
uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
db_name = os.getenv('MONGODB_DB_NAME', 'zenaipex')

async def fix():
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    upd = {'$unset': {'channel_id': ''}}
    result = await db.conversations.update_many({'direction': 'test-chat', 'channel_id': '6ab7c0adc39381e9f59801be'}, upd)
    print('Reverted', result.modified_count)

asyncio.run(fix())
