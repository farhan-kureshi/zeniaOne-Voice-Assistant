"""
Zenaipex AI — Public Widget API router.

GET  /api/v1/widget/config?identifier={id}
POST /api/v1/widget/chat
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging

from services.channel_service import get_channel_by_public_identifier
from services.conversation_service import create_conversation, add_message, get_conversation
from ai.rag import get_rag_pipeline
from ai.llm import AgentLLMClient
from core.database import col_agents, col_companies, col_conversations
from bson import ObjectId

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Widget (Public)"])


class WidgetChatRequest(BaseModel):
    identifier: str
    message: str
    history: List[Dict[str, str]] = []  # [{"role": "user", "content": "hello"}]
    conversation_id: Optional[str] = None


@router.get("/widget/config")
async def get_widget_config(identifier: str):
    """
    Get the public configuration for a chat widget.
    Never exposes API keys or internal IDs, only UI settings and agent name.
    """
    channel = await get_channel_by_public_identifier(identifier)
    if not channel or channel.get("type") != "web_chat":
        raise HTTPException(status_code=404, detail="Widget not found or inactive")

    agent = await col_agents().find_one({
        "_id": ObjectId(channel["agent_id"]),
        "company_id": channel["company_id"],
        "status": "active"
    })
    if not agent:
        raise HTTPException(status_code=404, detail="Agent inactive")

    # Get company to pass the name
    company = await col_companies().find_one({"_id": ObjectId(channel["company_id"])})
    if not company or not company.get("is_active", True):
        raise HTTPException(status_code=403, detail="Your account has been suspended. Please contact the administrator for assistance.")
    
    # Extract greeting message in default language
    lang = agent.get("default_language", "en-IN")
    greeting = agent.get("greeting_messages", {}).get(lang, "Hello! How can I help you today?")
    if company:
        greeting = greeting.format(company_name=company["name"])

    return {
        "agent_name": agent["name"],
        "greeting": greeting,
        "company_name": company["name"] if company else "Company",
        "primary_color": channel.get("config", {}).get("primary_color", "#2c3e50"),
    }


@router.post("/widget/chat")
async def widget_chat(req: WidgetChatRequest):
    """
    Process a chat message from the public widget.
    Fully tenant isolated via the public identifier.
    """
    if len(req.history) > 20:
        raise HTTPException(status_code=400, detail="Conversation history too long")
    if len(req.message) > 1000:
        raise HTTPException(status_code=400, detail="Message too long")

    # 1. Resolve channel & tenant
    channel = await get_channel_by_public_identifier(req.identifier)
    if not channel or channel.get("type") != "web_chat":
        raise HTTPException(status_code=404, detail="Widget not found or inactive")

    company_id = channel["company_id"]
    agent_id = channel["agent_id"]

    # 2. Load Agent
    agent = await col_agents().find_one({
        "_id": ObjectId(agent_id),
        "company_id": company_id,
        "status": "active"
    })
    if not agent:
        raise HTTPException(status_code=404, detail="Agent unavailable")

    company = await col_companies().find_one({"_id": ObjectId(company_id)})
    if not company or not company.get("is_active", True):
        raise HTTPException(status_code=403, detail="Your account has been suspended. Please contact the administrator for assistance.")

    # 3. Handle Conversation
    recent_conv = None
    if req.conversation_id and req.conversation_id != "tmp":
        if ObjectId.is_valid(req.conversation_id):
            recent_conv = await col_conversations().find_one({
                "company_id": company_id,
                "_id": ObjectId(req.conversation_id)
            })

    if not recent_conv:
        recent_conv = await create_conversation(
            company_id=company_id,
            agent_id=agent_id,
            channel_id=str(channel["_id"]),
            direction="inbound",
            language=agent.get("default_language", "en-IN")
        )
    
    conv_id = str(recent_conv["_id"])
    
    # Store user message
    await add_message(company_id, conv_id, "user", req.message)

    try:
        # 4. RAG Retrieval
        rag = get_rag_pipeline(company_id, agent)
        context_docs = None
        sources = []
        if rag.should_retrieve(req.message):
            context_docs = await rag.retrieve(req.message)
            sources = [doc["text"][:100] + "..." for doc in context_docs]

        # 5. LLM Call
        try:
            llm = await AgentLLMClient.create(agent)
        except RuntimeError as e:
            return {"answer": str(e), "sources": [], "conversation_id": conv_id}
            
        import time
        response_text, token_usage = await llm.generate(
            user_message=req.message,
            conversation_history=req.history,
            context_docs=context_docs,
            language=agent.get("default_language", "en-IN"),
        )
        
        # Store assistant message
        await add_message(company_id, conv_id, "assistant", response_text)

        return {
            "answer": response_text,
            "sources": sources,
            "conversation_id": conv_id
        }
    except Exception as e:
        logger.error(f"Widget chat error: {e}")
        return {"answer": "I'm having trouble connecting right now. Please try again.", "sources": [], "conversation_id": conv_id}
