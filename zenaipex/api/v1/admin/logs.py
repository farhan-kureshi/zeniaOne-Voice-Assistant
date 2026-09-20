from fastapi import APIRouter
from core.database import col_activity_logs

router = APIRouter(prefix="/logs")

@router.get("")
async def get_activity_logs(limit: int = 50):
    """Get the latest platform activity logs."""
    cursor = col_activity_logs().find({}).sort("created_at", -1).limit(limit)
    logs = []
    async for doc in cursor:
        logs.append({
            "id": str(doc["_id"]),
            "actor_name": doc.get("actor_name"),
            "actor_email": doc.get("actor_email"),
            "action": doc.get("action"),
            "target": doc.get("target"),
            "details": doc.get("details", ""),
            "created_at": doc.get("created_at")
        })
    return {"logs": logs}
