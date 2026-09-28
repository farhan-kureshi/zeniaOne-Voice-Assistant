"""
Zenaipex AI — FastAPI dependency injection.

Provides reusable dependencies for auth, tenant resolution, and plan enforcement.
"""
from fastapi import Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
from bson import ObjectId

from core.security import decode_access_token
from core.exceptions import (
    NotAuthenticatedError, InsufficientPermissionsError,
    TenantNotFoundError, TenantSuspendedError, TrialExpiredError,
    EmailNotVerifiedError,
)
from core.database import col_users, col_team_members, col_companies, col_subscriptions
from datetime import datetime, timezone

bearer_scheme = HTTPBearer(auto_error=False)


# ── Decoded Auth Context ──────────────────────────────────────────────────────

class AuthContext:
    """Carries the authenticated user + their current company context."""
    def __init__(
        self,
        user_id: str,
        user_doc: dict,
        company_id: Optional[str] = None,
        company_doc: Optional[dict] = None,
        role: Optional[str] = None,
    ):
        self.user_id = user_id
        self.user = user_doc
        self.company_id = company_id
        self.company = company_doc
        self.role = role  # "owner", "admin", "member", "viewer"

    @property
    def is_owner(self) -> bool:
        return self.role == "owner"

    @property
    def is_admin(self) -> bool:
        return self.role in ("owner", "admin")

    @property
    def is_member(self) -> bool:
        return self.role in ("owner", "admin", "member")


# ── Token Extraction ──────────────────────────────────────────────────────────

async def get_current_user_id(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
) -> str:
    """Extract and validate the JWT bearer token. Returns user_id string."""
    if not credentials:
        raise NotAuthenticatedError("Bearer token required")

    user_id = decode_access_token(credentials.credentials)
    if not user_id:
        raise NotAuthenticatedError("Invalid or expired token")

    return user_id


async def get_current_user(
    user_id: str = Depends(get_current_user_id),
) -> dict:
    """Load full user document from DB. Verifies user exists."""
    user = await col_users().find_one({"_id": ObjectId(user_id)})
    if not user:
        raise NotAuthenticatedError("User not found")
        
    # Auto-verify test users in non-production environments
    from core.config import settings
    if settings.app_env in ("development", "testing") and not user.get("is_verified", False):
        await col_users().update_one({"_id": user["_id"]}, {"$set": {"is_verified": True}})
        user["is_verified"] = True
        
    return user


async def get_verified_user(
    user: dict = Depends(get_current_user),
) -> dict:
    """Require verified email address."""
    if not user.get("is_verified", False):
        raise EmailNotVerifiedError()
    return user


async def get_platform_admin(
    user: dict = Depends(get_current_user),
) -> dict:
    """Require Platform Super Admin privileges."""
    if not user.get("is_platform_admin", False):
        raise InsufficientPermissionsError("Platform Super Admin privileges required")
    return user


# ── Tenant Resolution ─────────────────────────────────────────────────────────

async def get_auth_context(
    company_id: str,
    user: dict = Depends(get_current_user),
) -> AuthContext:
    """
    Resolve company context for the authenticated user.

    Validates:
    1. Company exists
    2. User is a team member of that company
    3. Company subscription is active (not suspended, not expired)

    Args:
        company_id: Company ObjectId string from URL path or query param

    Returns:
        AuthContext with user + company + role
    """
    if not user.get("is_platform_admin", False):
        if not user.get("is_verified", False):
            raise EmailNotVerifiedError()
    # Load company
    try:
        company = await col_companies().find_one({"_id": ObjectId(company_id)})
    except Exception:
        raise TenantNotFoundError()

    if not company:
        raise TenantNotFoundError()

    # Block access if company is suspended (Platform Admins bypass this)
    if not company.get("is_active", True) and not user.get("is_platform_admin", False):
        raise TenantSuspendedError()

    # Load team membership
    user_id = str(user["_id"])
    membership = await col_team_members().find_one({
        "company_id": company_id,
        "user_id": user_id,
    })

    if not membership:
        if user.get("is_platform_admin"):
            # Super Admin bypass: grant virtual owner role for View as Company
            membership = {"role": "owner"}
        else:
            raise InsufficientPermissionsError("You are not a member of this company")

    # Check subscription
    sub = await col_subscriptions().find_one({"company_id": company_id})
    if sub:
        if sub.get("status") == "suspended":
            raise TenantSuspendedError()

        # if sub.get("plan") == "free_trial":
        #     trial_ends = sub.get("trial_ends_at")
        #     if trial_ends:
        #         if trial_ends.tzinfo is None:
        #             trial_ends = trial_ends.replace(tzinfo=timezone.utc)
        #         if datetime.now(timezone.utc) > trial_ends:
        #             pass # raise TrialExpiredError() -> Unlimited Plan applied

    return AuthContext(
        user_id=user_id,
        user_doc=user,
        company_id=company_id,
        company_doc=company,
        role=membership.get("role", "member"),
    )


async def get_unverified_auth_context(
    company_id: str,
    user: dict = Depends(get_current_user),
) -> AuthContext:
    """
    Resolve company context for the authenticated user WITHOUT requiring email verification.
    This is STRICTLY for the onboarding flow and basic dashboard reads.
    """
    # Load company
    try:
        company = await col_companies().find_one({"_id": ObjectId(company_id)})
    except Exception:
        raise TenantNotFoundError()

    if not company:
        raise TenantNotFoundError()

    # Block access if company is suspended (Platform Admins bypass this)
    if not company.get("is_active", True) and not user.get("is_platform_admin", False):
        raise TenantSuspendedError()

    # Load team membership
    user_id = str(user["_id"])
    membership = await col_team_members().find_one({
        "company_id": company_id,
        "user_id": user_id,
    })

    if not membership:
        if user.get("is_platform_admin"):
            membership = {"role": "owner"}
        else:
            raise InsufficientPermissionsError("You are not a member of this company")

    return AuthContext(
        user_id=user_id,
        user_doc=user,
        company_id=company_id,
        company_doc=company,
        role=membership.get("role", "member"),
    )


def require_admin(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Require admin or owner role."""
    if not ctx.is_admin:
        raise InsufficientPermissionsError("Admin role required")
    return ctx


def require_onboarding_admin(ctx: AuthContext = Depends(get_unverified_auth_context)) -> AuthContext:
    """Require admin or owner role WITHOUT email verification (Onboarding only)."""
    if not ctx.is_admin:
        raise InsufficientPermissionsError("Admin role required")
    return ctx


def require_owner(ctx: AuthContext = Depends(get_auth_context)) -> AuthContext:
    """Require owner role."""
    if not ctx.is_owner:
        raise InsufficientPermissionsError("Owner role required")
    return ctx


# ── Twilio Webhook Resolution ─────────────────────────────────────────────────

async def resolve_company_from_slug(company_slug: str) -> dict:
    """
    Resolve a company document from its URL slug.
    Used in Twilio webhook paths: /webhook/twilio/{company_slug}/voice
    """
    company = await col_companies().find_one({"slug": company_slug})
    if not company:
        raise TenantNotFoundError()
    return company


async def resolve_company_from_phone(phone_number: str) -> Optional[dict]:
    """
    Resolve company by matching the Twilio phone number to a registered channel.
    Used at call time to identify which tenant owns a phone number.

    Returns:
        (company_doc, channel_doc) tuple or (None, None) if not found.
    """
    from core.database import col_channels
    channel = await col_channels().find_one({"phone_number": phone_number})
    if not channel:
        return None, None

    company = await col_companies().find_one({"_id": ObjectId(channel["company_id"])})
    return company, channel
