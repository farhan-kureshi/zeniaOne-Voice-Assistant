"""
Zenaipex AI — Channel service.

CRUD for communication channels (Twilio Voice, Web Chat, etc).
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from bson import ObjectId
import uuid
import logging

from core.database import col_channels, col_agents
from core.exceptions import NotFoundError, ConflictError

logger = logging.getLogger(__name__)


async def create_channel(company_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new communication channel."""
    # Verify agent exists and belongs to company
    agent_id = data.get("agent_id")
    if not agent_id:
        raise ValueError("agent_id is required")
        
    agent = await col_agents().find_one({
        "_id": ObjectId(agent_id),
        "company_id": company_id
    })
    if not agent:
        raise NotFoundError("Agent")

    # If phone number provided, ensure it's unique globally for active channels
    phone_number = data.get("phone_number")
    if phone_number:
        existing = await col_channels().find_one({
            "phone_number": phone_number,
            "is_active": True
        })
        if existing:
            raise ConflictError("Phone number is already in use by another active channel.")

    now = datetime.now(timezone.utc)
    channel_doc = {
        "company_id": company_id,
        "agent_id": agent_id,
        "name": data["name"],
        "type": data.get("type", "twilio_voice"),
        "phone_number": phone_number,
        "public_identifier": uuid.uuid4().hex,  # Safe public ID for web chat widgets
        
        # Twilio auth not implemented for bring-your-own in phase 2 yet, so leave blank
        "twilio_account_sid": None,
        "twilio_auth_token_encrypted": None,
        
        "webhook_base_url": data.get("webhook_base_url"),
        "config": data.get("config", {}),
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }

    result = await col_channels().insert_one(channel_doc)
    channel_doc["_id"] = result.inserted_id
    logger.info(f"Channel created: {data['name']} for company {company_id}")
    return channel_doc


async def get_channel(company_id: str, channel_id: str) -> Optional[Dict[str, Any]]:
    """Fetch channel by ID, scoped to company."""
    try:
        return await col_channels().find_one({
            "_id": ObjectId(channel_id),
            "company_id": company_id,
            "is_active": True,
        })
    except Exception:
        return None


async def get_channel_by_public_identifier(public_identifier: str) -> Optional[Dict[str, Any]]:
    """Fetch channel safely using its public widget identifier."""
    channel = await col_channels().find_one({
        "public_identifier": public_identifier,
        "is_active": True
    })
    if not channel and public_identifier in ("zeniaone", "default", "landing", "public"):
        # Look for platform admin_workspace web_chat channel or active agent
        channel = await col_channels().find_one({
            "company_id": "admin_workspace",
            "type": "web_chat",
            "is_active": True
        })
        if not channel:
            agent = await col_agents().find_one({"company_id": "admin_workspace", "status": "active"})
            if agent:
                now = datetime.now(timezone.utc)
                doc = {
                    "company_id": "admin_workspace",
                    "agent_id": str(agent["_id"]),
                    "name": "ZeniaOne Assistant",
                    "type": "web_chat",
                    "public_identifier": "zeniaone",
                    "config": {"primary_color": "#5F786D"},
                    "is_active": True,
                    "created_at": now,
                    "updated_at": now,
                }
                res = await col_channels().insert_one(doc)
                doc["_id"] = res.inserted_id
                return doc
    return channel


async def list_channels(
    company_id: str,
    type: Optional[str] = None,
    skip: int = 0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List all active channels for a company."""
    query: Dict[str, Any] = {"company_id": company_id, "is_active": True}
    if type:
        query["type"] = type
    return await col_channels().find(query).skip(skip).limit(limit).to_list(length=limit)


async def list_all_channels_admin(skip: int = 0, limit: int = 50) -> List[Dict[str, Any]]:
    """List all channels across all companies (for super admin)."""
    return await col_channels().find({}).skip(skip).limit(limit).to_list(length=limit)


async def update_channel(
    company_id: str,
    channel_id: str,
    updates: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Update channel fields."""
    # Remove None values
    updates = {k: v for k, v in updates.items() if v is not None}
    
    # If phone_number is being updated, verify it's unique
    if "phone_number" in updates and updates["phone_number"]:
        existing = await col_channels().find_one({
            "phone_number": updates["phone_number"],
            "is_active": True,
            "_id": {"$ne": ObjectId(channel_id)}
        })
        if existing:
            raise ConflictError("Phone number is already in use by another active channel.")
            
    # Verify agent if being updated
    if "agent_id" in updates and updates["agent_id"]:
        agent = await col_agents().find_one({
            "_id": ObjectId(updates["agent_id"]),
            "company_id": company_id
        })
        if not agent:
            raise NotFoundError("Agent")

    updates["updated_at"] = datetime.now(timezone.utc)

    return await col_channels().find_one_and_update(
        {"_id": ObjectId(channel_id), "company_id": company_id, "is_active": True},
        {"$set": updates},
        return_document=True,
    )


async def delete_channel(company_id: str, channel_id: str) -> bool:
    """Soft delete channel by setting is_active = False."""
    result = await col_channels().update_one(
        {"_id": ObjectId(channel_id), "company_id": company_id},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}}
    )
    return result.modified_count > 0
