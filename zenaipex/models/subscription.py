"""
Zenaipex AI — Subscription model.

Each company has exactly ONE subscription document. Subscription tracks
the plan, billing status, usage limits, and trial period.
"""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime, timedelta, timezone
from enum import Enum


class SubscriptionPlan(str, Enum):
    FREE_TRIAL = "free_trial"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    TRIAL = "trial"         # active trial
    SUSPENDED = "suspended"  # payment failure
    CANCELLED = "cancelled"


# Hardcoded plan limits — overridden by settings in production
PLAN_LIMITS: Dict[str, Dict[str, int]] = {
    "free_trial": {
        "ai_credits_per_month": 20,
        "call_minutes_per_month": 60,
        "max_agents": 1,
        "max_kb_docs": 10,
        "max_channels": 1,
        "max_team_members": 1,
    },
    "starter": {
        "ai_credits_per_month": 500,
        "call_minutes_per_month": 500,
        "max_agents": 3,
        "max_kb_docs": 100,
        "max_channels": 3,
        "max_team_members": 5,
    },
    "professional": {
        "ai_credits_per_month": 2000,
        "call_minutes_per_month": 2000,
        "max_agents": 10,
        "max_kb_docs": 1000,
        "max_channels": 10,
        "max_team_members": 25,
    },
    "enterprise": {
        "ai_credits_per_month": 999_999,
        "call_minutes_per_month": 999_999,
        "max_agents": 999_999,
        "max_kb_docs": 999_999,
        "max_channels": 999_999,
        "max_team_members": 999_999,
    },
}


class Subscription(BaseModel):
    """Subscription document as stored in MongoDB."""
    id: str
    company_id: str
    plan: SubscriptionPlan = SubscriptionPlan.FREE_TRIAL
    status: SubscriptionStatus = SubscriptionStatus.TRIAL

    # Trial window
    trial_starts_at: Optional[datetime] = None
    trial_ends_at: Optional[datetime] = None

    # Billing
    billing_email: Optional[str] = None
    billing_cycle: str = "monthly"   # "monthly" | "annual"
    next_billing_date: Optional[datetime] = None

    # Current limits (copied from PLAN_LIMITS on creation/upgrade)
    limits: Dict[str, int] = Field(default_factory=dict)

    created_at: datetime
    updated_at: datetime

    def is_trial_expired(self) -> bool:
        if self.plan != SubscriptionPlan.FREE_TRIAL:
            return False
        if not self.trial_ends_at:
            return False
        return datetime.now(timezone.utc) > self.trial_ends_at

    def get_limit(self, key: str) -> int:
        return self.limits.get(key, PLAN_LIMITS.get(self.plan, {}).get(key, 0))


class SubscriptionResponse(BaseModel):
    """API-safe subscription response."""
    plan: str
    status: str
    trial_ends_at: Optional[datetime] = None
    limits: Dict[str, int]
    billing_cycle: Optional[str] = None
    next_billing_date: Optional[datetime] = None
