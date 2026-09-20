"""
Zenaipex AI — Agent service.

CRUD for AI agents with full config management. Agents are always
scoped to a company_id — no cross-tenant access is possible.
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from bson import ObjectId
import logging

from core.database import col_agents, col_channels, col_knowledge_bases
from core.exceptions import NotFoundError, ConflictError
from services.tenant_service import enforce_plan_limit
from slugify import slugify

logger = logging.getLogger(__name__)


async def create_agent(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new AI agent for a company.

    Enforces plan limit on max_agents before creation.
    """
    await enforce_plan_limit(company_id, "max_agents")

    # Auto-generate slug from name
    base_slug = slugify(data.get("name", "agent"), max_length=60)
    slug = base_slug

    # Ensure slug unique within company
    counter = 1
    while await col_agents().find_one({"company_id": company_id, "slug": slug}):
        slug = f"{base_slug}-{counter}"
        counter += 1

    kb_id = data.get("knowledge_base_id")
    if kb_id:
        kb = await col_knowledge_bases().find_one({
            "_id": ObjectId(kb_id),
            "company_id": company_id,
        })
        if not kb:
            raise NotFoundError("Knowledge base")
    else:
        # Auto-link to the company's first available Knowledge Base if not specified
        kb = await col_knowledge_bases().find_one({"company_id": company_id})
        if kb:
            kb_id = str(kb["_id"])

    now = datetime.now(timezone.utc)
    agent_doc = {
        "company_id": company_id,
        "name": data["name"],
        "slug": slug,
        "description": data.get("description"),
        "agent_type": data.get("agent_type", "company_customer_agent"),
        "system_prompt": data["system_prompt"],
        "default_language": data.get("default_language", "en-IN"),
        "supported_languages": data.get("supported_languages", ["en-IN"]),
        "tts_voice": data.get("tts_voice", "anushka"),
        "tts_model": data.get("tts_model", "bulbul:v3"),
        "llm_model": data.get("llm_model", "sarvam-105b"),
        "llm_max_tokens": data.get("llm_max_tokens", 1200),
        "llm_temperature": data.get("llm_temperature", 0.3),
        "greeting_messages": data.get("greeting_messages", {}),
        "goodbye_messages": data.get("goodbye_messages", {}),
        "knowledge_base_id": kb_id,
        "max_conversation_turns": data.get("max_conversation_turns", 20),
        "silence_timeout_ms": data.get("silence_timeout_ms", 800),
        "force_process_timeout_sec": data.get("force_process_timeout_sec", 8.0),
        "enable_background_audio": data.get("enable_background_audio", True),
        "status": data.get("status", "draft"),
        "created_at": now,
        "updated_at": now,
    }

    result = await col_agents().insert_one(agent_doc)
    agent_doc["_id"] = result.inserted_id
    logger.info(f"Agent created: {data['name']} for company {company_id}")
    return agent_doc


async def get_agent(company_id: str, agent_id: str) -> Optional[Dict[str, Any]]:
    """Fetch agent by ID, scoped to company."""
    try:
        return await col_agents().find_one({
            "_id": ObjectId(agent_id),
            "company_id": company_id,
        })
    except Exception:
        return None


async def get_agent_by_slug(company_id: str, slug: str) -> Optional[Dict[str, Any]]:
    """Fetch agent by slug, scoped to company."""
    return await col_agents().find_one({"company_id": company_id, "slug": slug})


async def list_agents(
    company_id: str,
    status: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List all agents for a company, optionally filtered by status."""
    query: Dict[str, Any] = {"company_id": company_id}
    if status:
        query["status"] = status
    return await col_agents().find(query).skip(skip).limit(limit).to_list(length=limit)


async def update_agent(
    company_id: str,
    agent_id: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Update agent fields. Only non-None fields in updates are applied."""
    # Validate knowledge_base_id if being changed
    if "knowledge_base_id" in updates and updates["knowledge_base_id"]:
        kb_id = updates["knowledge_base_id"]
        kb = await col_knowledge_bases().find_one({
            "_id": ObjectId(kb_id),
            "company_id": company_id,
        })
        if not kb:
            raise NotFoundError("Knowledge base")

    updates["updated_at"] = datetime.now(timezone.utc)
    # Remove None values so we don't overwrite good data with None
    updates = {k: v for k, v in updates.items() if v is not None}

    result = await col_agents().find_one_and_update(
        {"_id": ObjectId(agent_id), "company_id": company_id},
        {"$set": updates},
        return_document=True,
    )
    return result


async def delete_agent(company_id: str, agent_id: str) -> bool:
    """
    Soft-delete an agent by setting status=deleted.
    Also deactivates any channels pointing to this agent.
    """
    result = await col_agents().update_one(
        {"_id": ObjectId(agent_id), "company_id": company_id},
        {"$set": {"status": "deleted", "updated_at": datetime.now(timezone.utc)}}
    )
    if result.modified_count > 0:
        # Deactivate channels using this agent
        await col_channels().update_many(
            {"agent_id": agent_id, "company_id": company_id},
            {"$set": {"is_active": False}}
        )
        return True
    return False


async def load_agent_for_call(phone_number: str) -> Optional[Dict[str, Any]]:
    """
    Resolve agent configuration from an inbound phone number.

    Call path: phone_number → Channel → Agent (with embedded KB namespace)

    Returns:
        Dict with 'agent', 'channel', 'company' keys, or None if not found.
    """
    from core.database import col_channels, col_companies
    
    # Find channel by phone number
    channel = await col_channels().find_one({"phone_number": phone_number, "is_active": True})
    if not channel:
        logger.warning(f"No active channel found for phone: {phone_number}")
        return None

    company_id = channel["company_id"]
    agent_id = channel["agent_id"]

    # Load agent
    agent = await col_agents().find_one({
        "_id": ObjectId(agent_id),
        "company_id": company_id,
        "status": "active",
    })
    if not agent:
        logger.warning(f"No active agent found: {agent_id}")
        return None

    # Load company
    company = await col_companies().find_one({"_id": ObjectId(company_id)})
    if not company or not company.get("is_active", True):
        logger.warning(f"Company {company_id} is suspended or not found")
        return None

    # Resolve knowledge base namespace
    kb_namespace = None
    if agent.get("knowledge_base_id"):
        kb = await col_knowledge_bases().find_one({
            "_id": ObjectId(agent["knowledge_base_id"]),
            "company_id": company_id,
        })
        if kb:
            kb_namespace = kb.get("pinecone_namespace")

    return {
        "agent": agent,
        "channel": channel,
        "company": company,
        "kb_namespace": kb_namespace,    # For Pinecone query namespacing
        "company_id": company_id,
    }
