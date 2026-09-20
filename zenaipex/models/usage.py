"""
Zenaipex AI — Usage tracking model.

One document per company per calendar month, upserted on every call completion.
Enforces plan limits and provides billing data.
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class UsageRecord(BaseModel):
    """Monthly usage document in MongoDB."""
    id: str
    company_id: str
    month: str              # "YYYY-MM", e.g. "2026-09"

    # Call usage
    call_minutes_used: float = 0.0
    call_count: int = 0
    inbound_call_count: int = 0
    outbound_call_count: int = 0
    
    # AI Credits
    ai_credits_used: float = 0.0

    # API usage (for cost tracking)
    stt_api_calls: int = 0
    tts_api_calls: int = 0
    llm_api_calls: int = 0
    rag_queries: int = 0

    # Knowledge base usage
    documents_indexed: int = 0

    # Last updated
    updated_at: datetime


class UsageSummary(BaseModel):
    """Usage summary returned by API — includes limit comparison."""
    month: str
    plan: str

    # Call usage
    call_minutes_used: float
    call_minutes_limit: int
    call_minutes_remaining: int
    call_count: int

    # AI Credits
    ai_credits_used: float
    ai_credits_limit: int
    ai_credits_remaining: int
    ai_credits_pct: float

    # Resource counts
    agents_used: int
    agents_limit: int
    kb_docs_used: int
    kb_docs_limit: int
    channels_used: int
    channels_limit: int

    # Percentages for dashboard progress bars
    call_minutes_pct: float     # 0.0–100.0


class UsageIncrementRequest(BaseModel):
    """Internal DTO for incrementing usage after a call."""
    company_id: str
    call_duration_seconds: float
    stt_calls: int = 0
    tts_calls: int = 0
    llm_calls: int = 0
    rag_queries: int = 0
    direction: str = "inbound"
