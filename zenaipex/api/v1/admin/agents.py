from fastapi import APIRouter
from core.database import col_agents, col_knowledge_bases
from bson import ObjectId

router = APIRouter(prefix="/agents")

def _fmt_agent(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "company_id": str(doc["company_id"]),
        "name": doc["name"],
        "tts_voice": doc.get("tts_voice"),
        "default_language": doc.get("default_language"),
        "status": doc.get("status", "draft"),
        "knowledge_base_id": doc.get("knowledge_base_id"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }

@router.get("")
async def list_agents():
    """List all agents across all companies."""
    cursor = col_agents().find({}).sort("created_at", -1)
    agents = []
    async for doc in cursor:
        agents.append(_fmt_agent(doc))
    return {"agents": agents}
