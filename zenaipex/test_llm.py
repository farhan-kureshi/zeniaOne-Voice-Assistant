import asyncio
import os
import sys

from core.database import connect_db, disconnect_db
from ai.llm import AgentLLMClient

async def main():
    await connect_db()
    
    # Just need an agent_id and company_id, can be fake for testing if not logging, 
    # but let's grab the admin agent
    from core.database import col_agents
    agent = await col_agents().find_one({"slug": "zeniaai-assistant"})
    if not agent:
        print("Agent not found!")
        return
        
    llm = await AgentLLMClient.create(agent)
    
    print("\n\n==== TEST 1: extract_intent ====")
    llm.set_budget(10.0) # 10s budget
    try:
        res = await llm.extract_intent("What features does ZeniaOne provide?")
        print(f"Intent result: {res}")
    except Exception as e:
        print(f"Intent failed: {e}")
        
    print("\n\n==== TEST 2: stream ====")
    llm.set_budget(10.0) # 10s budget
    try:
        messages = [{"role": "user", "content": "How does voice interaction work?"}]
        async for chunk in llm.stream(messages):
            pass
        print("Stream completed")
    except Exception as e:
        print(f"Stream failed: {e}")

    await disconnect_db()

if __name__ == "__main__":
    asyncio.run(main())
