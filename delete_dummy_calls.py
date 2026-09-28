import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv('zenaipex/.env')
uri = os.getenv('MONGODB_URI', 'mongodb://localhost:27017')
db_name = os.getenv('MONGODB_DB_NAME', 'zenaipex')

async def check():
    client = AsyncIOMotorClient(uri)
    db = client[db_name]
    convs = await db.conversations.find({'channel_id': '6ab7c0adc39381e9f59801be'}).to_list(length=None)
    
    to_delete = []
    for c in convs:
        d = c.get('started_at') or c.get('created_at')
        if not d:
            continue
        if isinstance(d, str):
            d = datetime.fromisoformat(d.replace('Z', '+00:00'))
        if d.year == 2026 and d.month == 9 and d.day < 26:
            to_delete.append(c['_id'])
            
    if to_delete:
        res = await db.conversations.delete_many({'_id': {'$in': to_delete}})
        print(f'Deleted {res.deleted_count} old dummy records.')
    else:
        print('No records found to delete.')

asyncio.run(check())
