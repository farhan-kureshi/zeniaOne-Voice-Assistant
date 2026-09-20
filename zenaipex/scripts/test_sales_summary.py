import asyncio
import os
import sys
from datetime import datetime, timezone
import httpx
from bson import ObjectId

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.database import connect_db, disconnect_db, col_leads, col_sales_calls, col_conversations, col_messages

COMPANY_ID = "6a990b403e9b17bef89acf87"
AGENT_ID = "6a990b403e9b17bef89acf89"
WEBHOOK_URL = f"http://127.0.0.1:8000/api/v1/companies/{COMPANY_ID}/sales-calls"

async def setup_call(scenario_name: str, messages: list):
    # 1. Create Lead
    lead = {
        "company_id": COMPANY_ID,
        "name": f"Test Lead - {scenario_name}",
        "phone": "+15550000000",
        "status": "new",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    lead_res = await col_leads().insert_one(lead)
    lead_id = str(lead_res.inserted_id)

    # 2. Create Conversation
    conv = {
        "company_id": COMPANY_ID,
        "agent_id": AGENT_ID,
        "direction": "outbound",
        "status": "completed",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    conv_res = await col_conversations().insert_one(conv)
    conv_id = str(conv_res.inserted_id)
    
    # 3. Create Messages
    for msg in messages:
        await col_messages().insert_one({
            "conversation_id": conv_id,
            "role": msg["role"],
            "text": msg["text"],
            "created_at": datetime.now(timezone.utc)
        })

    # 4. Create Sales Call
    call = {
        "company_id": COMPANY_ID,
        "lead_id": lead_id,
        "agent_id": AGENT_ID,
        "conversation_id": conv_id,
        "phone_number": "+15550000000",
        "direction": "outbound",
        "status": "in_progress",
        "started_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc)
    }
    call_res = await col_sales_calls().insert_one(call)
    call_id = str(call_res.inserted_id)

    return lead_id, call_id

async def test_scenario(scenario_name: str, messages: list):
    print(f"\n--- Running Scenario: {scenario_name} ---")
    lead_id, call_id = await setup_call(scenario_name, messages)
    
    # Trigger webhook
    async with httpx.AsyncClient() as client:
        url = f"{WEBHOOK_URL}/{call_id}/webhook"
        res = await client.post(url, json={"event": "completed"})
        print(f"Webhook Status: {res.status_code}")
    
    # Wait for background task
    summary = None
    for i in range(15):
        await asyncio.sleep(2)
        call = await col_sales_calls().find_one({"_id": ObjectId(call_id)})
        if call.get("call_summary"):
            summary = call.get("call_summary")
            break
            
    # Check DB
    lead = await col_leads().find_one({"_id": ObjectId(lead_id)})
    
    if summary:
        print(f"Summary Generated:")
        print(f"  Customer Need: {summary.get('customer_need')}")
        print(f"  Interested Products: {summary.get('interested_products')}")
        print(f"  Qualification: {summary.get('qualification_status')}")
        print(f"  Objections: {summary.get('objections')}")
        print(f"  Next Action: {summary.get('next_action')}")
        print(f"  Follow-up Required: {summary.get('followup_required')}")
        print(f"  Full Summary: {summary.get('full_summary')}")
    else:
        print("[FAILED] NO SUMMARY GENERATED")

    print(f"Lead Updates:")
    print(f"  Qualification: {lead.get('qualification')}")
    print(f"  Next Action: {lead.get('next_action')}")
    
    return call_id

async def test_failures(call_id: str):
    print(f"\n--- Running Failure & Idempotency Tests ---")
    
    # Idempotency: duplicate completed
    async with httpx.AsyncClient() as client:
        url = f"{WEBHOOK_URL}/{call_id}/webhook"
        res = await client.post(url, json={"event": "completed"})
        print(f"Duplicate Webhook Status: {res.status_code}")
        print(f"Response: {res.json()}")
        assert res.json().get("status") == "ignored", "Expected idempotency to ignore duplicate completed events"

async def main():
    await connect_db()
    
    scenarios = {
        "A: Product Inquiry": [
            {"role": "assistant", "text": "Hello! I am calling from Zenia. How can I help?"},
            {"role": "user", "text": "What is ZeniaHR?"}
        ],
        "B: Customer Need": [
            {"role": "assistant", "text": "Hello! I am calling from Zenia. How can I help?"},
            {"role": "user", "text": "We need attendance and payroll for 100 employees."}
        ],
        "C: Pricing Not Documented": [
            {"role": "assistant", "text": "Hello! I am calling from Zenia. How can I help?"},
            {"role": "user", "text": "How much does ZeniaHR cost?"}
        ],
        "D: Not Interested": [
            {"role": "assistant", "text": "Hello! I am calling from Zenia. Are you looking to upgrade your HR system?"},
            {"role": "user", "text": "I'm not interested."}
        ],
        "E: Hindi": [
            {"role": "assistant", "text": "Namaste! Zenia se baat kar rahi hu."},
            {"role": "user", "text": "Mujhe naya attendance system chahiye."}
        ],
        "F: Gujarati": [
            {"role": "assistant", "text": "Namaste! Zenia thi vaat karu chu."},
            {"role": "user", "text": "Mhare navo payroll system joie che."}
        ]
    }
    
    last_call_id = None
    for name, messages in scenarios.items():
        last_call_id = await test_scenario(name, messages)
        
    await test_failures(last_call_id)
        
    await disconnect_db()

if __name__ == "__main__":
    asyncio.run(main())
