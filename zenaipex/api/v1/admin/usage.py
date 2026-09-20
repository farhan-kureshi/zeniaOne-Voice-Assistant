from fastapi import APIRouter
from core.database import col_usage_records, col_companies
from bson import ObjectId
from datetime import datetime, timezone

router = APIRouter(prefix="/usage")

@router.get("")
async def list_usage():
    """List all usage records for the current month."""
    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    
    # We will fetch all usage records, but only return the current month by default
    cursor = col_usage_records().find({"month": current_month}).sort("updated_at", -1)
    
    records = []
    async for doc in cursor:
        record = {
            "id": str(doc["_id"]),
            "company_id": doc["company_id"],
            "month": doc["month"],
            "call_minutes_used": doc.get("call_minutes_used", 0.0),
            "call_count": doc.get("call_count", 0),
            "stt_api_calls": doc.get("stt_api_calls", 0),
            "tts_api_calls": doc.get("tts_api_calls", 0),
            "llm_api_calls": doc.get("llm_api_calls", 0),
            "rag_queries": doc.get("rag_queries", 0),
            "updated_at": doc.get("updated_at"),
        }
        
        # Attach company name
        company = await col_companies().find_one({"_id": ObjectId(doc["company_id"])})
        if company:
            record["company_name"] = company.get("name", "Unknown")
        else:
            record["company_name"] = "Unknown"
            
        records.append(record)
        
    return {"usage_records": records, "month": current_month}
