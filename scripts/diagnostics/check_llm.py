import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
async def main():
    client = AsyncIOMotorClient('mongodb://localhost:27017/')
    db = client['zenaipex']
    requests = await db['llm_requests'].find().sort('_id', -1).limit(20).to_list(length=20)
    for r in requests:
        print(f"[{r.get('request_id')}] [{r.get('direction')}] {r.get('provider')} - Latency: {r.get('latency_ms')}ms")
asyncio.run(main())
