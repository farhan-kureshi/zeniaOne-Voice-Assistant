import asyncio
import time
import logging
import sys

sys.path.append('D:\\Sarvam-Voice-Agent-main\\zenaipex')
from core.database import connect_db, disconnect_db
from api.v1.agents import agent_test_chat, AgentTestChatRequest

logging.basicConfig(level=logging.INFO)

async def main():
    await connect_db()
    
    company_id = '6a990b403e9b17bef89acf87'
    agent_id = '6a990b403e9b17bef89acf8b'
    
    queries = [
        "Payroll aur attendance ka relationship kya hai?",
        "Net salary kaise calculate hoti hai?",
        "ZeniaHR kis type ke external systems se connect kar sakta hai?"
    ]
    
    class MockAuthContext:
        def __init__(self):
            self.user = {"id": "mock", "name": "Mock"}
            
        def dict(self):
            return {"user": self.user}
            
        def get(self, key, default=None):
            return getattr(self, key, default)
            
    for q in queries:
        print(f"\n--- Testing: {q} ---")
        req = AgentTestChatRequest(
            message=q,
            history=[],
            language="en-IN"
        )
        
        start_time = time.perf_counter()
        
        try:
            resp = await agent_test_chat(
                company_id=company_id,
                agent_id=agent_id,
                body=req,
                ctx=MockAuthContext()
            )
            elapsed = time.perf_counter() - start_time
            print(f"Total Latency: {elapsed:.2f}s")
            print(f"Answer:\n{resp.get('answer', 'No answer key')}")
            print(f"Fallback Occurred: {resp.get('is_fallback', False)}")
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            print(f"FAILED. Total Latency: {elapsed:.2f}s")
            print(f"Error: {str(e)}")
            
    await disconnect_db()

asyncio.run(main())
