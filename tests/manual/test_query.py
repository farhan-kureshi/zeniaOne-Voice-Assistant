import os
import sys
import asyncio
import httpx
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "zenaipex")))

from zenaipex.core.database import connect_db, col_agents, col_users
from zenaipex.core.security import create_access_token

async def get_test_data():
    await connect_db()
    agent = await col_agents().find_one({"status": "active"})
    user = await col_users().find_one()
    return str(agent.get("company_id")), str(agent.get("_id")), str(user.get("_id"))

def run():
    company_id, agent_id, user_id = asyncio.run(get_test_data())
    token = create_access_token({"sub": user_id})
    
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    
    q = "Payroll aur attendance ka relationship kya hai?"
    
    print(f"\n--- QUERY 1 ---")
    print(f"Q: {q}")
    payload = {"message": q, "conversation_id": None}
    
    try:
        start_t = time.perf_counter()
        resp = httpx.post(f"http://localhost:8000/api/v1/companies/{company_id}/agents/{agent_id}/test-chat", json=payload, headers=headers, timeout=120.0)
        elapsed = time.perf_counter() - start_t
        print(f"Status: {resp.status_code}")
        print(f"Client Latency: {elapsed:.2f}s")
        if resp.status_code == 200:
            data = resp.json()
            print(f"Answer: {data.get('answer', '')[:100]}...")
        else:
            print(f"Error: {resp.text}")
    except Exception as e:
        print(f"Request failed: {e}")

if __name__ == "__main__":
    run()
