import asyncio
import logging
import sys
import os

# Add zenaipex to path for imports
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from zenaipex.ai.rag import TenantRAGPipeline

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test():
    r = TenantRAGPipeline(namespace='staging-603d2b5b9f1b2c3d4e5f6a7b', agent_doc={"knowledge_base_id": "123"})
    
    queries = [
        "What is ZeniaHR?",
        "What modules do you have?",
        "How much does it cost?",
        "Do you have an attendance module?",
        "ZeniaHR kya hai?"
    ]
    
    for q in queries:
        print(f"\n--- QUERY: {q} ---")
        res = await r.retrieve(q)
        print(f"RETRIEVED:\n{res}")

if __name__ == "__main__":
    asyncio.run(test())
