"""
Zenaipex AI — Communication Channel model.

A Channel is a phone number or messaging endpoint associated with one Agent.
When Twilio receives a call to a phone number, we resolve:
  phone_number → Channel → Agent → KnowledgeBase + system_prompt
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class ChannelType(str, Enum):
    TWILIO_VOICE = "twilio_voice"
    WHATSAPP = "whatsapp"       # Future
    WEB_CHAT = "web_chat"       # Future
    SMS = "sms"                 # Future


class ChannelCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100,
                      description="Friendly name, e.g. 'Main Inbound Number'")
    type: ChannelType = ChannelType.TWILIO_VOICE
    agent_id: str = Field(..., description="MongoDB _id of the Agent to use on this channel")

    # Twilio voice channel config
    phone_number: Optional[str] = Field(
        default=None,
        description="E.164 format, e.g. +919876543210"
    )

    # If company brings their own Twilio account (Phase 3 feature)
    # In Phase 2, these default to platform Twilio credentials
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None   # stored encrypted

    # Webhook override (defaults to platform webhook)
    webhook_base_url: Optional[str] = None

    # Extra config (channel-type-specific)
    config: Dict[str, Any] = Field(default_factory=dict)


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    agent_id: Optional[str] = None
    phone_number: Optional[str] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    is_active: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


class Channel(BaseModel):
    """Channel document as stored in MongoDB."""
    id: str
    company_id: str
    agent_id: str
    name: str
    type: ChannelType = ChannelType.TWILIO_VOICE
    phone_number: Optional[str] = None
    public_identifier: Optional[str] = None

    # Twilio creds — None means use platform defaults
    # twilio_auth_token is stored encrypted in DB
    twilio_account_sid: Optional[str] = None
    twilio_auth_token_encrypted: Optional[str] = None

    webhook_base_url: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    created_at: datetime
    updated_at: datetime

    class Config:
        use_enum_values = True


class ChannelResponse(BaseModel):
    """API response — never returns raw Twilio auth token."""
    id: str
    company_id: str
    agent_id: str
    name: str
    type: str
    phone_number: Optional[str] = None
    public_identifier: Optional[str] = None
    has_custom_twilio: bool = False    # True if company provided own creds
    is_active: bool
    created_at: datetime
    updated_at: datetime
