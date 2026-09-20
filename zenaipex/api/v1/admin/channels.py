"""
Admin Channels API.
"""
from fastapi import APIRouter, Query
from typing import Optional

from services import channel_service

router = APIRouter()

@router.get("/channels", summary="List all channels across platform")
async def list_all_channels(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=100, le=500),
):
    channels = await channel_service.list_all_channels_admin(skip=skip, limit=limit)
    
    def _fmt(doc):
        return {
            "id": str(doc["_id"]),
            "company_id": doc["company_id"],
            "agent_id": doc["agent_id"],
            "name": doc["name"],
            "type": doc["type"],
            "phone_number": doc.get("phone_number"),
            "public_identifier": doc.get("public_identifier"),
            "is_active": doc.get("is_active", True),
            "created_at": doc.get("created_at"),
            "updated_at": doc.get("updated_at"),
        }
        
    return {"channels": [_fmt(c) for c in channels], "count": len(channels)}
