import asyncio
import time
from bson import ObjectId
import json
import logging
import sys

sys.path.append('D:\\Sarvam-Voice-Agent-main\\zenaipex')
from zenaipex.core.database import connect_db, disconnect_db, get_db
from zenaipex.ai.llm import AgentLLMClient

logging.basicConfig(level=logging.INFO)

async def main():
    await connect_db()
    db = get_db()
    
    agent = await db['agents'].find_one({'_id': ObjectId('6a990b403e9b17bef89acf8b')})
    if not agent:
        print("Agent not found.")
        await disconnect_db()
        return
        
    print("Agent loaded successfully.")
    
    llm_client = await AgentLLMClient.create(agent, request_id="REQ-DIAG-01")
    all_providers = llm_client.providers
    print(f"Configured Providers: {[p.provider for p in all_providers]}")
    
    messages = [
        {"role": "system", "content": "You are a helpful HR assistant. Answer based on context."},
        {"role": "user", "content": "Context: Attendance data is sent to the payroll engine to calculate net salary. Query: Payroll aur attendance ka relationship kya hai?"}
    ]
    
    results = []
    
    for p in all_providers:
        p_name = p.provider.lower()
        if p_name == 'groq':
            print("\nSkipping Groq as requested.")
            continue
            
        print(f"\n--- Testing Provider: {p_name.upper()} ---")
        llm_client.providers = [p]
        llm_client.request_id = f"REQ-DIAG-{p_name.upper()}"
        llm_client.set_budget(35.0) 
        
        try:
            start_time = time.perf_counter()
            content, usage = await llm_client.generate(messages, stage="generation")
            elapsed = time.perf_counter() - start_time
            
            print(f"Status: SUCCESS")
            print(f"Total Latency: {elapsed:.2f}s")
            
            results.append({
                "provider": p_name,
                "status": "SUCCESS",
                "latency": f"{elapsed:.2f}s",
                "answer": content[:100]
            })
        except Exception as e:
            elapsed = time.perf_counter() - start_time
            print(f"Status: FAILED")
            print(f"Total Latency: {elapsed:.2f}s")
            print(f"Exception: {str(e)}")
            results.append({
                "provider": p_name,
                "status": "FAILED",
                "latency": f"{elapsed:.2f}s",
                "error": str(e)
            })
            
    await llm_client.close()
    await disconnect_db()
    
    print("\n--- Summary ---")
    for r in results:
        print(r)

asyncio.run(main())
