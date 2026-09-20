import asyncio
import httpx
from pymongo import MongoClient
from bson import ObjectId
import datetime

# Setup DB
client = MongoClient("mongodb://localhost:27017/")
db = client["zenaipex"]

company_id = "6a990b403e9b17bef89acf87"
agent_id = "6a990b403e9b17bef89acf8b"

# Ensure agent has sales enabled
db.agents.update_one(
    {"_id": ObjectId(agent_id)},
    {"$set": {"sales_config": {"sales_enabled": True}}}
)

# 1. Create a mock lead directly in DB to bypass auth
lead_doc = {
    "company_id": company_id,
    "name": "Test User",
    "phone": "+919876543210",
    "email": "test@example.com",
    "status": "new",
    "created_at": datetime.datetime.utcnow(),
    "updated_at": datetime.datetime.utcnow()
}
res = db.leads.insert_one(lead_doc)
lead_id = str(res.inserted_id)
print(f"Created lead: {lead_id}")

# 2. Create a Sales Call directly in DB
call_doc = {
    "company_id": company_id,
    "lead_id": lead_id,
    "agent_id": agent_id,
    "phone_number": "+919876543210",
    "status": "scheduled",
    "direction": "outbound",
    "lead_name": "Test User",
    "source": "api",
    "created_at": datetime.datetime.utcnow(),
    "updated_at": datetime.datetime.utcnow(),
    "duration_seconds": 0
}
res = db.sales_calls.insert_one(call_doc)
call_id = str(res.inserted_id)
print(f"Created sales call: {call_id}")

async def test_flow():
    # 3. Use the MockProvider
    # We must add zenaipex to path since this script is in zenaipex/scripts/
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    from modules.telephony.mock_provider import MockTelephonyProvider
    from core.database import connect_db, disconnect_db
    await connect_db()
    
    provider = MockTelephonyProvider()
    
    webhook_url = f"http://127.0.0.1:8000/api/v1/companies/{company_id}/sales-calls/{call_id}/webhook"
    
    print(f"Initiating call with webhook: {webhook_url}")
    provider_call_id = await provider.create_call(
        to_phone="+919876543210",
        from_phone="system_default",
        webhook_url=webhook_url,
        metadata={"sales_call_id": call_id}
    )
    
    print(f"Provider Call ID: {provider_call_id}")
    
    # Wait for the mock provider to finish simulating the call (takes ~4-5 seconds)
    print("Waiting for mock simulation to complete...")
    for _ in range(30):
        await asyncio.sleep(1)
        status = await provider.get_call_status(provider_call_id)
        if status == "completed":
            print("Mock simulation completed.")
            break
            
    print("Test finished.")

if __name__ == "__main__":
    asyncio.run(test_flow())
