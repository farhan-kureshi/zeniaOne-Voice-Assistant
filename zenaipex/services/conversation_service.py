"""
Zenaipex AI — Conversation service.

CRUD for conversations (call sessions) and messages (transcript turns).
All data is strictly scoped to company_id.
"""
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from bson import ObjectId

from core.database import col_conversations, col_messages

logger = logging.getLogger(__name__)


async def create_conversation(
    company_id: str,
    agent_id: str,
    channel_id: Optional[str] = None,
    call_sid: Optional[str] = None,
    caller_phone: Optional[str] = None,
    caller_to: Optional[str] = None,
    direction: str = "inbound",
    language: str = "en-IN",
    scheduled_call_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Create a new conversation record at call start."""
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": company_id,      # TENANT ISOLATION KEY
        "agent_id": agent_id,
        "channel_id": channel_id,
        "call_sid": call_sid,
        "caller_phone": caller_phone,
        "caller_to": caller_to,
        "direction": direction,
        "language": language,
        "status": "active",
        "started_at": now,
        "ended_at": None,
        "duration_seconds": 0,
        "turn_count": 0,
        "booking_confirmed": False,
        "appointment_data": None,
        "scheduled_call_id": scheduled_call_id,
        "is_pinned": False,
    }
    if call_sid:
        existing = await col_conversations().find_one({"call_sid": call_sid})
        if existing:
            # Update only if not already set, or just return it
            # Actually, let's just return the existing if it's already there
            return existing

    result = await col_conversations().insert_one(doc)
    doc["_id"] = result.inserted_id
    return doc


async def end_conversation(
    company_id: str,
    conversation_id: str,
    status: str = "completed",
    appointment_data: Optional[Dict[str, Any]] = None,
    booking_confirmed: bool = False,
) -> bool:
    """Mark conversation as completed/failed and record end metadata."""
    conv = await col_conversations().find_one({
        "_id": ObjectId(conversation_id),
        "company_id": company_id,
    })
    if not conv:
        return False

    end_time = datetime.now(timezone.utc)
    started_at = conv.get("started_at")
    if started_at:
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)
        duration = (end_time - started_at).total_seconds()
    else:
        duration = 0

    updates: Dict[str, Any] = {
        "status": status,
        "ended_at": end_time,
        "duration_seconds": int(duration),
        "booking_confirmed": booking_confirmed,
    }
    if appointment_data:
        updates["appointment_data"] = appointment_data

    await col_conversations().update_one(
        {"_id": ObjectId(conversation_id)},
        {"$set": updates},
    )
    return True


async def add_message(
    company_id: str,
    conversation_id: str,
    role: str,           # "user" | "assistant" | "system"
    text: str,
    language: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Append a transcript turn to a conversation."""
    now = datetime.now(timezone.utc)
    doc = {
        "company_id": company_id,      # TENANT ISOLATION KEY
        "conversation_id": conversation_id,
        "role": role,
        "text": text,
        "language": language,
        "timestamp": now,
        "metadata": metadata or {},
    }
    result = await col_messages().insert_one(doc)
    doc["_id"] = result.inserted_id

    # Increment turn count
    await col_conversations().update_one(
        {"_id": ObjectId(conversation_id)},
        {"$inc": {"turn_count": 1}}
    )
    return doc


async def get_conversation(company_id: str, conversation_id: str) -> Optional[Dict[str, Any]]:
    """Fetch conversation by ID, scoped to company."""
    try:
        return await col_conversations().find_one({
            "_id": ObjectId(conversation_id),
            "company_id": company_id,
        })
    except Exception:
        return None


async def get_conversation_messages(
    company_id: str,
    conversation_id: str,
) -> List[Dict[str, Any]]:
    """Fetch all messages for a conversation, scoped to company."""
    return await col_messages().find({
        "company_id": company_id,
        "conversation_id": conversation_id,
    }).sort("timestamp", 1).to_list(length=1000)


async def list_conversations(
    company_id: str,
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    is_archived: Optional[bool] = False,
    skip: int = 0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List conversations for a company, with optional filters."""
    query: Dict[str, Any] = {"company_id": company_id}
    if agent_id:
        query["agent_id"] = agent_id
    if status:
        query["status"] = status
    if is_archived is not None:
        if is_archived:
            query["is_archived"] = True
        else:
            query["$or"] = [{"is_archived": False}, {"is_archived": {"$exists": False}}]

    return await col_conversations().find(query).sort(
        "started_at", -1
    ).skip(skip).limit(limit).to_list(length=limit)

async def archive_conversation(company_id: str, conversation_id: str) -> bool:
    """Archive a conversation."""
    result = await col_conversations().update_one(
        {"_id": ObjectId(conversation_id), "company_id": company_id},
        {"$set": {"is_archived": True}}
    )
    return result.modified_count > 0

async def restore_conversation(company_id: str, conversation_id: str) -> bool:
    """Restore an archived conversation."""
    result = await col_conversations().update_one(
        {"_id": ObjectId(conversation_id), "company_id": company_id},
        {"$set": {"is_archived": False}}
    )
    return result.modified_count > 0

async def delete_conversation(company_id: str, conversation_id: str) -> bool:
    """Hard delete a conversation and its messages."""
    result = await col_conversations().delete_one(
        {"_id": ObjectId(conversation_id), "company_id": company_id}
    )
    if result.deleted_count > 0:
        from core.database import col_messages
        await col_messages().delete_many({"conversation_id": conversation_id})
        return True
    return False

async def find_conversation_by_call_sid(company_id: str, call_sid: str) -> Optional[Dict[str, Any]]:
    """Look up conversation by Twilio CallSid, scoped to company."""
    return await col_conversations().find_one({
        "company_id": company_id,
        "call_sid": call_sid,
    })

async def pin_conversation(company_id: str, conversation_id: str) -> bool:
    """Pin a conversation."""
    result = await col_conversations().update_one(
        {"_id": ObjectId(conversation_id), "company_id": company_id},
        {"$set": {"is_pinned": True}}
    )
    return result.modified_count > 0

async def unpin_conversation(company_id: str, conversation_id: str) -> bool:
    """Unpin a conversation."""
    result = await col_conversations().update_one(
        {"_id": ObjectId(conversation_id), "company_id": company_id},
        {"$set": {"is_pinned": False}}
    )
    return result.modified_count > 0

async def bulk_archive_conversations(company_id: str, conversation_ids: List[str]) -> int:
    """Archive multiple conversations."""
    object_ids = [ObjectId(cid) for cid in conversation_ids if ObjectId.is_valid(cid)]
    if not object_ids:
        return 0
    result = await col_conversations().update_many(
        {"_id": {"$in": object_ids}, "company_id": company_id},
        {"$set": {"is_archived": True}}
    )
    return result.modified_count

async def bulk_delete_conversations(company_id: str, conversation_ids: List[str]) -> int:
    """Delete multiple conversations and their messages."""
    object_ids = [ObjectId(cid) for cid in conversation_ids if ObjectId.is_valid(cid)]
    if not object_ids:
        return 0
    result = await col_conversations().delete_many(
        {"_id": {"$in": object_ids}, "company_id": company_id}
    )
    
    if result.deleted_count > 0:
        from core.database import col_messages
        # We need the string versions of IDs for message deletion, or whichever format they're saved in
        # We use string representation for conversation_id in messages
        str_ids = [str(oid) for oid in object_ids]
        await col_messages().delete_many(
            {"conversation_id": {"$in": str_ids}, "company_id": company_id}
        )
    return result.deleted_count

