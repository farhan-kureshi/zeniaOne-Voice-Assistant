"""
Zenaipex AI — Tenant service.

CRUD operations for companies, team members, and subscriptions.
All queries are company_id scoped. This is the single source of
truth for tenant-level data access.
"""
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from bson import ObjectId
import logging

from core.database import (
    col_companies, col_team_members, col_subscriptions, col_users,
    col_agents, col_channels, col_knowledge_bases,
)
from core.exceptions import (
    ConflictError, NotFoundError, InsufficientPermissionsError,
    PlanLimitExceededError,
)
from models.subscription import PLAN_LIMITS

logger = logging.getLogger(__name__)


# ── Company CRUD ──────────────────────────────────────────────────────────────

async def get_company(company_id: str) -> Optional[Dict[str, Any]]:
    """Fetch company document by ID."""
    try:
        doc = await col_companies().find_one({"_id": ObjectId(company_id)})
        return doc
    except Exception:
        return None


async def get_company_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch company by URL slug."""
    return await col_companies().find_one({"slug": slug})


async def update_company(company_id: str, updates: Dict[str, Any]) -> bool:
    """Update mutable company fields."""
    updates["updated_at"] = datetime.now(timezone.utc)
    result = await col_companies().update_one(
        {"_id": ObjectId(company_id)},
        {"$set": updates}
    )
    return result.modified_count > 0


async def get_user_companies(user_id: str) -> List[Dict[str, Any]]:
    """
    Return all companies the user is a member of.
    Includes membership role for each company.
    """
    memberships = await col_team_members().find({"user_id": user_id}).to_list(length=100)
    if not memberships:
        return []

    company_ids = [ObjectId(m["company_id"]) for m in memberships]
    companies = await col_companies().find({"_id": {"$in": company_ids}}).to_list(length=100)

    # Attach role to each company
    membership_map = {m["company_id"]: m["role"] for m in memberships}
    for company in companies:
        company["user_role"] = membership_map.get(str(company["_id"]))

    return companies


# ── Team Members ──────────────────────────────────────────────────────────────

async def get_team_members(company_id: str) -> List[Dict[str, Any]]:
    """Return all team members with their user profiles."""
    memberships = await col_team_members().find({"company_id": company_id}).to_list(length=500)

    # Fetch user profiles
    user_ids = [ObjectId(m["user_id"]) for m in memberships]
    users = await col_users().find({"_id": {"$in": user_ids}}).to_list(length=500)
    user_map = {str(u["_id"]): u for u in users}

    result = []
    for m in memberships:
        user = user_map.get(m["user_id"], {})
        result.append({
            "user_id": m["user_id"],
            "email": user.get("email", ""),
            "name": user.get("name", ""),
            "role": m["role"],
            "joined_at": m["joined_at"],
        })
    return result


async def invite_team_member(
    company_id: str,
    inviter_role: str,
    email: str,
    role: str,
) -> Dict[str, Any]:
    """
    Add a user to a company. Creates user account if not exists.

    Enforces: only admins/owners can invite, plan member limits.
    """
    # Check inviter permissions
    if inviter_role not in ("owner", "admin"):
        raise InsufficientPermissionsError("Only admins can invite team members")

    # Check plan member limit
    await enforce_plan_limit(company_id, "max_team_members")

    # Find or note user
    user = await col_users().find_one({"email": email.lower()})
    if not user:
        raise NotFoundError(f"No Zenaipex account found for {email}. "
                            "Ask them to register first.")

    user_id = str(user["_id"])

    # Check not already a member
    existing = await col_team_members().find_one({
        "company_id": company_id,
        "user_id": user_id,
    })
    if existing:
        raise ConflictError(f"{email} is already a team member")

    now = datetime.now(timezone.utc)
    await col_team_members().insert_one({
        "company_id": company_id,
        "user_id": user_id,
        "role": role,
        "joined_at": now,
    })
    logger.info(f"Team member added: {email} → {company_id} ({role})")
    return {"user_id": user_id, "email": email, "role": role}


async def remove_team_member(company_id: str, target_user_id: str, requester_role: str):
    """Remove a team member. Owners cannot be removed."""
    if requester_role not in ("owner", "admin"):
        raise InsufficientPermissionsError("Only admins can remove members")

    member = await col_team_members().find_one({
        "company_id": company_id,
        "user_id": target_user_id,
    })
    if not member:
        raise NotFoundError("Team member")
    if member["role"] == "owner":
        raise InsufficientPermissionsError("Cannot remove the company owner")

    await col_team_members().delete_one({"company_id": company_id, "user_id": target_user_id})


async def update_member_role(
    company_id: str,
    target_user_id: str,
    new_role: str,
    requester_role: str,
):
    """Update a team member's role. Only owners can promote to admin."""
    if new_role == "owner":
        raise InsufficientPermissionsError("Cannot assign owner role via API")
    if requester_role not in ("owner", "admin"):
        raise InsufficientPermissionsError("Only admins can change roles")

    result = await col_team_members().update_one(
        {"company_id": company_id, "user_id": target_user_id},
        {"$set": {"role": new_role}},
    )
    if result.matched_count == 0:
        raise NotFoundError("Team member")


# ── Subscription ──────────────────────────────────────────────────────────────

async def get_subscription(company_id: str) -> Optional[Dict[str, Any]]:
    """Fetch subscription document for a company."""
    return await col_subscriptions().find_one({"company_id": company_id})


async def upgrade_plan(company_id: str, new_plan: str) -> bool:
    """
    Upgrade company to a new plan. Updates subscription limits.
    In Phase 2, payment is handled externally (webhook updates this).
    """
    valid_plans = ("free_trial", "starter", "professional", "enterprise")
    if new_plan not in valid_plans:
        raise NotFoundError(f"Plan '{new_plan}'")

    limits = PLAN_LIMITS.get(new_plan, {})
    now = datetime.now(timezone.utc)

    result = await col_subscriptions().update_one(
        {"company_id": company_id},
        {"$set": {
            "plan": new_plan,
            "status": "active",
            "limits": limits,
            "updated_at": now,
        }}
    )
    # Also update company.plan for fast reads
    await col_companies().update_one(
        {"_id": ObjectId(company_id)},
        {"$set": {"plan": new_plan, "updated_at": now}}
    )
    return result.modified_count > 0


# ── Plan Limit Enforcement ────────────────────────────────────────────────────

async def enforce_plan_limit(company_id: str, resource_key: str):
    """
    Check if company has hit their plan limit for a resource.
    Raises PlanLimitExceededError if limit reached.

    resource_key: one of "max_agents", "max_kb_docs", "max_channels", "max_team_members"
    """
    sub = await get_subscription(company_id)
    if not sub:
        return  # No subscription = no limits (shouldn't happen in prod)

    limits = sub.get("limits", PLAN_LIMITS.get(sub.get("plan", "free_trial"), {}))
    limit = limits.get(resource_key, 0)

    if limit >= 999_999:
        return  # Enterprise: unlimited

    # Count current resources
    count = 0
    if resource_key == "max_agents":
        count = await col_agents().count_documents({"company_id": company_id, "status": {"$ne": "deleted"}})
    elif resource_key == "max_channels":
        count = await col_channels().count_documents({"company_id": company_id})
    elif resource_key == "max_team_members":
        count = await col_team_members().count_documents({"company_id": company_id})
    elif resource_key == "max_kb_docs":
        count = await col_knowledge_bases().count_documents({"company_id": company_id})

    if count >= limit:
        plan = sub.get("plan", "free_trial")
        raise PlanLimitExceededError(resource_key.replace("max_", ""), limit, plan)
