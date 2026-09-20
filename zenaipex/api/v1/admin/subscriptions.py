from fastapi import APIRouter
from core.database import col_subscriptions, col_companies
from bson import ObjectId

router = APIRouter(prefix="/subscriptions")

@router.get("")
async def list_subscriptions():
    """List all subscriptions across all companies."""
    cursor = col_subscriptions().find({}).sort("created_at", -1)
    subscriptions = []
    async for doc in cursor:
        sub = {
            "id": str(doc["_id"]),
            "company_id": doc["company_id"],
            "plan": doc.get("plan", "free_trial"),
            "status": doc.get("status", "trial"),
            "trial_ends_at": doc.get("trial_ends_at"),
            "limits": doc.get("limits", {}),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
            "billing_cycle": doc.get("billing_cycle", "monthly"),
            "next_billing_date": doc.get("next_billing_date"),
        }
        
        # Attach company name
        company = await col_companies().find_one({"_id": ObjectId(doc["company_id"])})
        if company:
            sub["company_name"] = company.get("name", "Unknown")
        else:
            sub["company_name"] = "Unknown"
            
        subscriptions.append(sub)
        
    return {"subscriptions": subscriptions}
