from fastapi import APIRouter, Depends, Path, Query
from core.database import col_conversations
from core.dependencies import get_auth_context, AuthContext, get_platform_admin
from core.exceptions import NotFoundError
from services import conversation_service
from typing import Optional
from bson import ObjectId

router = APIRouter(prefix="/conversations", tags=["Admin Conversations"])

def _fmt_conv(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "company_id": str(doc["company_id"]),
        "agent_id": str(doc["agent_id"]) if doc.get("agent_id") else None,
        "caller_phone": doc.get("caller_phone"),
        "direction": doc.get("direction", "inbound"),
        "language": doc.get("language", "en-IN"),
        "status": doc.get("status", "completed"),
        "is_archived": doc.get("is_archived", False),
        "is_pinned": doc.get("is_pinned", False),
        "started_at": doc.get("started_at"),
        "ended_at": doc.get("ended_at"),
        "duration_seconds": doc.get("duration_seconds", 0),
        "turn_count": doc.get("turn_count", 0),
        "title": doc.get("title", "New Chat"),
        "message_count": doc.get("message_count", 0),
    }

@router.get("")
async def list_conversations(
    company_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    is_archived: Optional[bool] = Query(default=False),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
    user: dict = Depends(get_platform_admin),
):
    """List all conversations across all companies."""
    query = {}
    if company_id:
        query["company_id"] = company_id
    if status:
        query["status"] = status
    if is_archived is not None:
        if is_archived:
            query["is_archived"] = True
        else:
            query["$or"] = [{"is_archived": False}, {"is_archived": {"$exists": False}}]

    cursor = col_conversations().find(query).sort("started_at", -1).skip(skip).limit(limit)
    convs = []
    
    from core.database import col_messages
    async for doc in cursor:
        fmt = _fmt_conv(doc)
        
        first_msg = await col_messages().find_one(
            {"conversation_id": str(doc["_id"]), "role": "user"},
            sort=[("timestamp", 1)]
        )
        last_msg = await col_messages().find_one(
            {"conversation_id": str(doc["_id"])},
            sort=[("timestamp", -1)]
        )
        
        msg_count = await col_messages().count_documents({"conversation_id": str(doc["_id"])})
        fmt["message_count"] = msg_count
        
        if first_msg:
            fmt["first_message_at"] = first_msg.get("timestamp")
        if last_msg:
            fmt["last_message_at"] = last_msg.get("timestamp")
            
        if fmt["direction"] in ("test-chat", "inbound"):
            fmt["title"] = doc.get("title") or (first_msg.get("text", "New Chat") if first_msg else "New Chat")
            fmt["last_message"] = last_msg.get("text", "") if last_msg else ""

        convs.append(fmt)
        
    return {"conversations": convs, "count": len(convs)}


@router.post("/{company_id}/{conv_id}/archive")
async def archive_conversation(
    company_id: str = Path(...),
    conv_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Mark a conversation as archived."""
    success = await conversation_service.archive_conversation(company_id, conv_id)
    if not success:
        raise NotFoundError("Conversation")
    return {"success": True}


@router.post("/{company_id}/{conv_id}/restore")
async def restore_conversation(
    company_id: str = Path(...),
    conv_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Restore a conversation from the archive."""
    success = await conversation_service.restore_conversation(company_id, conv_id)
    if not success:
        raise NotFoundError("Conversation")
    return {"success": True}


@router.delete("/{company_id}/{conv_id}")
async def delete_conversation(
    company_id: str = Path(...),
    conv_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Hard delete a conversation and its messages."""
    success = await conversation_service.delete_conversation(company_id, conv_id)
    if not success:
        raise NotFoundError("Conversation")
    return {"success": True}

@router.post("/{company_id}/{conv_id}/pin")
async def pin_conversation(
    company_id: str = Path(...),
    conv_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Pin a conversation."""
    success = await conversation_service.pin_conversation(company_id, conv_id)
    if not success:
        raise NotFoundError("Conversation")
    return {"success": True}

@router.post("/{company_id}/{conv_id}/unpin")
async def unpin_conversation(
    company_id: str = Path(...),
    conv_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Unpin a conversation."""
    success = await conversation_service.unpin_conversation(company_id, conv_id)
    if not success:
        raise NotFoundError("Conversation")
    return {"success": True}

from pydantic import BaseModel
class AdminBulkIdsRequest(BaseModel):
    conversations: list[dict] # {"company_id": str, "id": str}

@router.post("/bulk-archive")
async def bulk_archive(
    req: AdminBulkIdsRequest,
    user: dict = Depends(get_platform_admin),
):
    """Archive multiple conversations across companies."""
    # group by company
    from collections import defaultdict
    grouped = defaultdict(list)
    for c in req.conversations:
        grouped[c["company_id"]].append(c["id"])
    count = 0
    for comp_id, ids in grouped.items():
        count += await conversation_service.bulk_archive_conversations(comp_id, ids)
    return {"success": True, "count": count}

@router.post("/bulk-delete")
async def bulk_delete(
    req: AdminBulkIdsRequest,
    user: dict = Depends(get_platform_admin),
):
    """Delete multiple conversations across companies."""
    from collections import defaultdict
    grouped = defaultdict(list)
    for c in req.conversations:
        grouped[c["company_id"]].append(c["id"])
    count = 0
    for comp_id, ids in grouped.items():
        count += await conversation_service.bulk_delete_conversations(comp_id, ids)
    return {"success": True, "count": count}

