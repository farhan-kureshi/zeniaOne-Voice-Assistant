"""
Zenaipex AI — Conversation and Message models.

A Conversation is a single call session.
Messages are the individual transcript turns within a conversation.
"""
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ConversationStatus(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Conversation(BaseModel):
    """Conversation document in MongoDB."""
    id: str
    company_id: str        # TENANT ISOLATION KEY — on every document
    agent_id: str
    channel_id: Optional[str] = None

    # Call metadata
    call_sid: Optional[str] = None          # Twilio CallSid
    caller_phone: Optional[str] = None
    direction: str = "inbound"              # "inbound" | "outbound" | "reminder"
    language: str = "en-IN"

    # Status tracking
    status: ConversationStatus = ConversationStatus.ACTIVE
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: int = 0
    is_pinned: bool = False

    # Stats
    turn_count: int = 0
    booking_confirmed: bool = False

    # Appointment extracted (if any)
    appointment_data: Optional[Dict[str, Any]] = None

    # Scheduling (if this was a scheduled/reminder call)
    scheduled_call_id: Optional[str] = None

    class Config:
        use_enum_values = True


class ConversationResponse(BaseModel):
    id: str
    company_id: str
    agent_id: str
    caller_phone: Optional[str] = None
    direction: str
    language: str
    status: str
    started_at: datetime
    ended_at: Optional[datetime] = None
    duration_seconds: int
    turn_count: int
    booking_confirmed: bool
    is_pinned: bool = False
    appointment_data: Optional[Dict[str, Any]] = None


class Message(BaseModel):
    """Individual transcript turn in MongoDB."""
    id: str
    company_id: str           # TENANT ISOLATION KEY
    conversation_id: str
    role: MessageRole
    text: str
    language: Optional[str] = None
    timestamp: datetime
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    text: str
    language: Optional[str] = None
    timestamp: datetime


class ConversationWithMessages(BaseModel):
    """Conversation + full transcript (for detail view)."""
    conversation: ConversationResponse
    messages: List[MessageResponse]
