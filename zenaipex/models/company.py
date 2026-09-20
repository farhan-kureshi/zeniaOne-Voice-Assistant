"""
Zenaipex AI — Company (tenant) model.

A Company is the top-level tenant entity. Every piece of data in the
platform belongs to exactly one Company, enforced via company_id on
every MongoDB document and every Pinecone namespace.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any
from datetime import datetime, timezone
from enum import Enum
from slugify import slugify


class CompanyPlan(str, Enum):
    FREE_TRIAL = "free_trial"
    STARTER = "starter"
    PROFESSIONAL = "professional"
    ENTERPRISE = "enterprise"


class CompanyCreate(BaseModel):
    """Fields required to create a new company (during signup)."""
    name: str = Field(..., min_length=2, max_length=100)
    # slug is auto-generated from name if not provided
    slug: Optional[str] = Field(default=None, min_length=2, max_length=60)
    # Industry / use-case hint (optional, for onboarding)
    industry: Optional[str] = Field(default=None, max_length=100)
    # Country code
    country: str = Field(default="IN", max_length=5)
    # Timezone
    timezone: str = Field(default="Asia/Kolkata")

    @field_validator("slug", mode="before")
    @classmethod
    def auto_slug(cls, v, info):
        """Auto-generate slug from name if not provided."""
        if not v:
            name = info.data.get("name", "")
            return slugify(name, max_length=60)
        return slugify(v, max_length=60)


class CompanyUpdate(BaseModel):
    """Mutable fields on a company."""
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    industry: Optional[str] = None
    country: Optional[str] = None
    timezone: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None


class Company(BaseModel):
    """Full company document (as stored in MongoDB)."""
    id: str                                     # str(_id)
    name: str
    slug: str
    industry: Optional[str] = None
    country: str = "IN"
    timezone: str = "Asia/Kolkata"
    plan: CompanyPlan = CompanyPlan.FREE_TRIAL
    is_active: bool = True
    settings: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    class Config:
        use_enum_values = True


class CompanyResponse(BaseModel):
    """API response for a company (safe to return to client)."""
    id: str
    name: str
    slug: str
    industry: Optional[str] = None
    country: str
    timezone: str
    plan: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── TeamMember model ──────────────────────────────────────────────────────────

class TeamRole(str, Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


class TeamMemberCreate(BaseModel):
    """Invite a user to a company."""
    email: str
    role: TeamRole = TeamRole.MEMBER


class TeamMemberResponse(BaseModel):
    """Team member as returned by API."""
    user_id: str
    email: str
    name: Optional[str] = None
    role: str
    joined_at: datetime
