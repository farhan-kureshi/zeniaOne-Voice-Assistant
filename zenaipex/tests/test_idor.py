import asyncio
from zenaipex.core.database import connect_db, col_users, col_companies, col_team_members, col_agents
from zenaipex.core.security import create_access_token
from bson import ObjectId
from fastapi.testclient import TestClient
from zenaipex.main import app
import sys

def run_test_sync():
    
    # Run async setup
    async def setup():
        await connect_db()
        comp_a = await col_companies().insert_one({"name": "Company A", "plan": "enterprise"})
        comp_b = await col_companies().insert_one({"name": "Company B", "plan": "enterprise"})
        user_a = await col_users().insert_one({"email": "usera@example.com", "is_verified": True})
        await col_team_members().insert_one({"company_id": str(comp_a.inserted_id), "user_id": str(user_a.inserted_id), "role": "owner"})
        agent_b = await col_agents().insert_one({"company_id": str(comp_b.inserted_id), "name": "Agent B", "status": "active"})
        token = create_access_token({"sub": str(user_a.inserted_id)})
        return comp_a, comp_b, user_a, agent_b, token
        
    comp_a, comp_b, user_a, agent_b, token = asyncio.run(setup())
    
    client = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}
    
    print("Testing IDOR boundaries...")
    res1 = client.get(f"/api/v1/companies/{comp_b.inserted_id}/agents", headers=headers)
    print(f"1. Accessing Company B directly via its company_id (Should be 403 or 404): {res1.status_code}")
    
    res2 = client.get(f"/api/v1/companies/{comp_a.inserted_id}/agents/{agent_b.inserted_id}", headers=headers)
    print(f"2. Accessing Company B's agent via Company A's company_id (Should be 404 Not Found): {res2.status_code}")
    
    res3 = client.get(f"/api/v1/admin/usage", headers=headers)
    print(f"3. Accessing Super Admin functionality (Should be 403): {res3.status_code}")

    async def cleanup():
        await col_companies().delete_many({"_id": {"$in": [comp_a.inserted_id, comp_b.inserted_id]}})
        await col_users().delete_many({"_id": user_a.inserted_id})
        await col_team_members().delete_many({"company_id": str(comp_a.inserted_id)})
        await col_agents().delete_many({"_id": agent_b.inserted_id})
        
    asyncio.run(cleanup())

if __name__ == "__main__":
    run_test_sync()
