from pydantic import BaseModel, Field, EmailStr
from typing import Optional, List
from datetime import datetime
from enum import Enum

class CallStatus(str, Enum):
    SCHEDULED = "scheduled"
    QUEUED = "queued"
    RINGING = "ringing"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    NO_ANSWER = "no_answer"

class LeadCreate(BaseModel):
    name: str = Field(..., max_length=150)
    phone: str = Field(..., max_length=20)
    email: Optional[EmailStr] = None
    company_name: Optional[str] = Field(default=None, max_length=150)
    source: Optional[str] = Field(default="api", max_length=50)
    preferred_call_time: Optional[datetime] = None
    notes: Optional[str] = None

class LeadResponse(LeadCreate):
    id: str
    company_id: str
    status: str = "new"
    created_at: datetime
    updated_at: datetime

class SalesCallCreate(BaseModel):
    lead_id: str
    agent_id: str
    scheduled_at: Optional[datetime] = None
    phone_number: str

class SalesCallSummary(BaseModel):
    customer_need: Optional[str] = None
    interested_products: List[str] = Field(default_factory=list)
    qualification_status: Optional[str] = None
    objections: List[str] = Field(default_factory=list)
    next_action: Optional[str] = None
    followup_required: bool = False
    full_summary: Optional[str] = None

class SalesCallResponse(BaseModel):
    id: str
    company_id: str
    agent_id: str
    lead_id: str
    conversation_id: Optional[str] = None
    direction: str = "outbound"
    status: CallStatus
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    duration_seconds: int = 0
    phone_number: str
    lead_name: Optional[str] = None
    lead_email: Optional[str] = None
    source: str = "api"
    call_summary: Optional[SalesCallSummary] = None
    qualification: Optional[str] = None
    next_action: Optional[str] = None
    created_at: datetime
    updated_at: datetime
