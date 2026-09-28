import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from bson import ObjectId
from dotenv import load_dotenv

load_dotenv('zenaipex/.env')
uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
db_name = os.getenv('MONGODB_DB_NAME', 'zenaipex')

async def fix():
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    
    res = await db.conversations.update_one(
        {'_id': ObjectId('6ab9f8ebb22bca99a954f529')},
        {'$set': {
            'status': 'completed',
        }}
    )
    print(f'Fixed {res.modified_count} record.')

asyncio.run(fix())
