import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017/')
    db = client['zenaipex']
    msgs = await db['messages'].find({'role': 'user'}).sort('_id', -1).limit(5).to_list(length=5)
    for m in msgs:
        print(m.keys())
        print(m.get('text', m.get('message', 'No text key found')))
asyncio.run(main())
