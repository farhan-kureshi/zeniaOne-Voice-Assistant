"""
Zenaipex AI — Conversations API router.

GET /api/v1/companies/{id}/conversations              List conversations
GET /api/v1/companies/{id}/conversations/{cid}        Get conversation
GET /api/v1/companies/{id}/conversations/{cid}/messages  Get transcript
GET /api/v1/companies/{id}/usage                      Get usage summary
"""
from fastapi import APIRouter, Depends, Path, Query, HTTPException
from typing import Optional

from core.dependencies import get_auth_context, AuthContext
from core.exceptions import NotFoundError, InsufficientPermissionsError
from services import conversation_service
from services.channel_service import get_channel
from pydantic import BaseModel
import time
from ai.rag import get_rag_pipeline
from ai.llm import AgentLLMClient
from core.database import col_agents, col_companies
from bson import ObjectId

class ChatRequest(BaseModel):
    message: str
from services.usage_service import get_usage_summary

router = APIRouter(tags=["Conversations & Usage"])


def _fmt_conv(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "company_id": doc["company_id"],
        "agent_id": doc.get("agent_id"),
        "caller_phone": doc.get("caller_phone"),
        "direction": doc.get("direction", "inbound"),
        "language": doc.get("language", "en-IN"),
        "status": doc.get("status", "completed"),
        "started_at": doc.get("started_at"),
        "ended_at": doc.get("ended_at"),
        "duration_seconds": doc.get("duration_seconds", 0),
        "turn_count": doc.get("turn_count", 0),
        "booking_confirmed": doc.get("booking_confirmed", False),
        "is_pinned": doc.get("is_pinned", False),
        "appointment_data": doc.get("appointment_data"),
        "call_sid": doc.get("call_sid"),
        "recording_url": doc.get("recording_url"),
        "recording_sid": doc.get("recording_sid"),
        "caller_to": doc.get("caller_to"),
        "title": doc.get("title"),
        "last_message": doc.get("last_message"),
    }


def _fmt_msg(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "conversation_id": doc["conversation_id"],
        "role": doc.get("role", "user"),
        "text": doc.get("text") or doc.get("content", ""),
        "language": doc.get("language"),
        "timestamp": doc.get("timestamp"),
    }


@router.get(
    "/companies/{company_id}/conversations",
    summary="List conversations",
)
async def list_conversations(
    company_id: str = Path(...),
    agent_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    is_archived: Optional[bool] = Query(default=False),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=200),
    ctx: AuthContext = Depends(get_auth_context),
):
    """
    List call conversations for the company, newest first.
    Optional filters: agent_id, status (active/completed/failed), is_archived.
    """
    convs = await conversation_service.list_conversations(
        company_id=company_id,
        agent_id=agent_id,
        status=status,
        is_archived=is_archived,
        skip=skip,
        limit=limit,
    )
    
    formatted_convs = []
    from core.database import col_messages
    for c in convs:
        fmt = _fmt_conv(c)
        
        # Fetch first and last message for metadata and title
        first_msg = await col_messages().find_one(
            {"conversation_id": str(c["_id"]), "role": "user"},
            sort=[("timestamp", 1)]
        )
        last_msg = await col_messages().find_one(
            {"conversation_id": str(c["_id"])},
            sort=[("timestamp", -1)]
        )
        
        msg_count = await col_messages().count_documents({"conversation_id": str(c["_id"])})
        fmt["message_count"] = msg_count
        
        if first_msg:
            fmt["first_message_at"] = first_msg.get("timestamp")
        if last_msg:
            fmt["last_message_at"] = last_msg.get("timestamp")
            
        if fmt["direction"] == "test-chat" or fmt["direction"] == "inbound":
            # Use existing title if available, otherwise fallback to first user message text
            first_text = first_msg.get("text") or first_msg.get("content") or "New Chat" if first_msg else "New Chat"
            fmt["title"] = c.get("title") or first_text
            last_text = last_msg.get("text") or last_msg.get("content", "") if last_msg else ""
            fmt["last_message"] = last_text
            
        formatted_convs.append(fmt)

    return {"conversations": formatted_convs, "count": len(convs)}


@router.get(
    "/companies/{company_id}/conversations/{conv_id}",
    summary="Get conversation details",
)
async def get_conversation(
    company_id: str = Path(...),
    conv_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Get metadata for a single conversation."""
    conv = await conversation_service.get_conversation(company_id, conv_id)
    if not conv:
        raise NotFoundError("Conversation")
    return _fmt_conv(conv)


@router.get(
    "/companies/{company_id}/conversations/{conv_id}/messages",
    summary="Get conversation transcript",
)
async def get_messages(
    company_id: str = Path(...),
    conv_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Get the full transcript (turn-by-turn messages) for a conversation."""
    # Verify conversation belongs to company
    conv = await conversation_service.get_conversation(company_id, conv_id)
    if not conv:
        raise NotFoundError("Conversation")

    messages = await conversation_service.get_conversation_messages(company_id, conv_id)
    return {
        "conversation_id": conv_id,
        "messages": [_fmt_msg(m) for m in messages],
        "count": len(messages),
    }


# ── POST Routes for Dashboard Chat ──────────────────────────────────────────────

@router.post(
    "/companies/{company_id}/channels/{channel_id}/conversations",
    summary="Create a new conversation for a channel",
)
async def create_new_conversation(
    company_id: str = Path(...),
    channel_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    if not ctx.is_member:
        raise InsufficientPermissionsError("Must be a team member")
        
    channel = await get_channel(company_id, channel_id)
    if not channel:
        raise NotFoundError("Channel")
        
    agent = await col_agents().find_one({"_id": ObjectId(channel["agent_id"]), "company_id": company_id})
    if not agent:
        raise NotFoundError("Agent")
        
    conv = await conversation_service.create_conversation(
        company_id=company_id,
        agent_id=channel["agent_id"],
        channel_id=channel_id,
        direction="inbound", # or web-chat
        language=agent.get("default_language", "en-IN")
    )
    return _fmt_conv(conv)


@router.post(
    "/companies/{company_id}/conversations/{conv_id}/chat",
    summary="Send a chat message",
)
async def chat_in_conversation(
    req: ChatRequest,
    company_id: str = Path(...),
    conv_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    if not ctx.is_member:
        raise InsufficientPermissionsError("Must be a team member")
        
    from bson import ObjectId
    if not ObjectId.is_valid(conv_id):
        raise NotFoundError("Conversation")
        
    conv = await conversation_service.get_conversation(company_id, conv_id)
    if not conv:
        raise NotFoundError("Conversation")
        
    agent = await col_agents().find_one({"_id": ObjectId(conv["agent_id"]), "company_id": company_id})
    if not agent:
        raise NotFoundError("Agent")
        
    company = await col_companies().find_one({"_id": ObjectId(company_id)})
    
    messages = await conversation_service.get_conversation_messages(company_id, conv_id)
    history = [{"role": m["role"], "content": m.get("text", "")} for m in messages]
    
    # ALWAYS Save user msg first
    await conversation_service.add_message(company_id, conv_id, "user", req.message)
    
    context_docs = None
    sources = []
    from ai.language_detector import detect_language as _detect_lang
    _lang_result = _detect_lang(req.message, history)
    
    from ai.fast_path import check_deterministic_fast_path
    fast_response = check_deterministic_fast_path(
        message=req.message,
        company=company,
        agent=agent,
        detected_lang=_lang_result.lang,
        detected_script=_lang_result.script
    )
    
    if fast_response:
        response_text = fast_response
        await conversation_service.add_message(company_id, conv_id, "assistant", response_text)
        return {"answer": response_text, "sources": []}
    
    try:
        rag = get_rag_pipeline(company_id, agent)
        if rag.should_retrieve(req.message):
            context_docs = await rag.retrieve(req.message)
            sources = [doc["text"][:100] + "..." for doc in context_docs]
            
        llm = await AgentLLMClient.create(agent)
        response_text, _ = await llm.generate(
            user_message=req.message,
            conversation_history=history,
            context_docs=context_docs,
            language=agent.get("default_language", "en-IN"),
            current_date=time.strftime("%A, %B %d, %Y"),
            company_name=company["name"] if company else "Company"
        )
        if not response_text:
            response_text = "⚠️ Error: All providers unavailable"
            
        await conversation_service.add_message(company_id, conv_id, "assistant", response_text)
    except Exception as e:
        # Catch ANY error (Pinecone, OpenAI, Timeout) and return 500 cleanly 
        # so frontend knows it failed but the user message is saved.
        import logging
        logging.error(f"AI Generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    return {
        "answer": response_text,
        "sources": sources
    }

# ── Conversation Management ─────────────────────────────────────────────────────

@router.post(
    "/companies/{company_id}/conversations/{conv_id}/archive",
    summary="Archive a conversation",
)
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


@router.post(
    "/companies/{company_id}/conversations/{conv_id}/restore",
    summary="Restore an archived conversation",
)
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


@router.delete(
    "/companies/{company_id}/conversations/{conv_id}",
    summary="Delete a conversation",
)
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

@router.post(
    "/companies/{company_id}/conversations/{conv_id}/pin",
    summary="Pin a conversation",
)
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

@router.post(
    "/companies/{company_id}/conversations/{conv_id}/unpin",
    summary="Unpin a conversation",
)
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

class BulkIdsRequest(BaseModel):
    conversation_ids: list[str]

@router.post(
    "/companies/{company_id}/conversations/bulk-archive",
    summary="Archive multiple conversations",
)
async def bulk_archive(
    req: BulkIdsRequest,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Archive multiple conversations."""
    count = await conversation_service.bulk_archive_conversations(company_id, req.conversation_ids)
    return {"success": True, "count": count}

@router.post(
    "/companies/{company_id}/conversations/bulk-delete",
    summary="Delete multiple conversations",
)
async def bulk_delete(
    req: BulkIdsRequest,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Delete multiple conversations."""
    count = await conversation_service.bulk_delete_conversations(company_id, req.conversation_ids)
    return {"success": True, "count": count}

# ── Usage ─────────────────────────────────────────────────────────────────────

@router.get(
    "/companies/{company_id}/usage",
    summary="Get usage summary",
)
async def get_usage(
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """
    Get current month's usage statistics and plan limits.
    Used by the dashboard to render progress bars and alerts.
    """
    return await get_usage_summary(company_id)
