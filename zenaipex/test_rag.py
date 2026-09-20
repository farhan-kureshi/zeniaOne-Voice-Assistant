import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from ai.rag import TenantRAGPipeline

async def main():
    rag = TenantRAGPipeline("6a990b403e9b17bef89acf87", "6a990b403e9b17bef89acf8b")
    docs = await rag.retrieve("Payroll aur attendance ka relationship kya hai?", limit=5)
    print(f"Retrieval Count: {len(docs)}")
    if docs:
        print(f"Top Score: {docs[0].get('score')}")
        print(f"Top Topic: {docs[0].get('metadata', {}).get('topic')}")
        
asyncio.run(main())
