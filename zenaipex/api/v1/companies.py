"""
Zenaipex AI — Companies API router.

GET    /api/v1/companies                   List user's companies
POST   /api/v1/companies                   Create a new company
GET    /api/v1/companies/{id}              Get company details
PATCH  /api/v1/companies/{id}             Update company
GET    /api/v1/companies/{id}/subscription Get subscription + limits
GET    /api/v1/companies/{id}/team        List team members
POST   /api/v1/companies/{id}/team        Invite team member
PATCH  /api/v1/companies/{id}/team/{uid}  Update member role
DELETE /api/v1/companies/{id}/team/{uid}  Remove team member
"""
from fastapi import APIRouter, Depends, Path, UploadFile, File, HTTPException
from typing import List, Optional
from bson import ObjectId
from datetime import datetime, timezone
import os

from core.dependencies import (
    get_verified_user, get_current_user, get_auth_context, require_admin, require_owner,
    require_onboarding_admin, get_unverified_auth_context, AuthContext,
)
from core.database import col_companies, col_subscriptions, col_team_members
from core.exceptions import NotFoundError
from services.storage_service import save_upload, delete_file
from models.company import CompanyCreate, CompanyUpdate, TeamMemberCreate
from services import tenant_service
from services.usage_service import get_usage_summary
from slugify import slugify

router = APIRouter(prefix="/companies", tags=["Companies"])


def _fmt_company(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "name": doc["name"],
        "slug": doc["slug"],
        "industry": doc.get("industry"),
        "country": doc.get("country", "IN"),
        "timezone": doc.get("timezone", "Asia/Kolkata"),
        "plan": doc.get("plan", "free_trial"),
        "is_active": doc.get("is_active", True),
        "user_role": doc.get("user_role"),
        "settings": doc.get("settings", {}),
        "onboarding_completed": doc.get("settings", {}).get("onboarding_completed", True),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


@router.get("", summary="List my companies")
async def list_companies(user: dict = Depends(get_current_user)):
    """List all companies the authenticated user belongs to."""
    user_id = str(user["_id"])
    companies = await tenant_service.get_user_companies(user_id)
    return {"companies": [_fmt_company(c) for c in companies]}


@router.post("", status_code=201, summary="Create a new company")
async def create_company(
    body: CompanyCreate,
    user: dict = Depends(get_verified_user),
):
    """
    Create a new company. The caller becomes the Owner.
    A Free Trial subscription is auto-created.
    """
    from services.auth_service import register_user
    # Use the sub-flow from auth_service that creates company + sub + membership
    user_id = str(user["_id"])
    slug = body.slug or slugify(body.name, max_length=60)

    # Ensure slug uniqueness
    now = datetime.now(timezone.utc)
    if await col_companies().find_one({"slug": slug}):
        slug = f"{slug}-{int(now.timestamp())}"

    from models.subscription import PLAN_LIMITS
    company_doc = {
        "name": body.name,
        "slug": slug,
        "industry": body.industry,
        "country": body.country,
        "timezone": body.timezone,
        "plan": "free_trial",
        "is_active": True,
        "settings": {"onboarding_completed": False},
        "created_at": now,
        "updated_at": now,
    }
    result = await col_companies().insert_one(company_doc)
    company_id = str(result.inserted_id)

    # Create owner membership
    await col_team_members().insert_one({
        "company_id": company_id,
        "user_id": user_id,
        "role": "owner",
        "joined_at": now,
    })

    # Create subscription
    from core.config import settings as cfg
    from datetime import timedelta
    trial_end = now + timedelta(days=cfg.free_trial_days)
    await col_subscriptions().insert_one({
        "company_id": company_id,
        "plan": "free_trial",
        "status": "trial",
        "trial_starts_at": now,
        "trial_ends_at": trial_end,
        "limits": PLAN_LIMITS["free_trial"],
        "billing_cycle": "monthly",
        "created_at": now,
        "updated_at": now,
    })

    company_doc["_id"] = result.inserted_id
    return _fmt_company(company_doc)


@router.get("/{company_id}", summary="Get company details")
async def get_company(
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """Get full company details. Must be a member."""
    return _fmt_company(ctx.company)


@router.patch("/{company_id}", summary="Update company")
async def update_company(
    body: CompanyUpdate,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_onboarding_admin),
):
    """Update company settings. Requires admin role."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    
    is_verified = ctx.user.get("is_verified", False)
    
    if not is_verified:
        allowed_top_level = {"name", "industry", "country", "timezone", "settings"}
        updates = {k: v for k, v in updates.items() if k in allowed_top_level}
        
        if "settings" in updates and isinstance(updates["settings"], dict):
            allowed_settings = {
                "business_email", "phone", "website", "address", "legal_name",
                "default_agent", "default_language", "default_voice",
                "business_hours", "greeting_message"
            }
            # Merge safely with existing DB settings to avoid overwriting sensitive fields
            company = await tenant_service.get_company(company_id)
            db_settings = company.get("settings", {}) if company else {}
            
            for k in allowed_settings:
                if k in updates["settings"]:
                    db_settings[k] = updates["settings"][k]
                    
            if "business_hours" in db_settings and isinstance(db_settings["business_hours"], str):
                import json
                try:
                    bh = json.loads(db_settings["business_hours"])
                    # Normalize to 7 days
                    days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                    for day in days:
                        if day not in bh:
                            bh[day] = {"isOpen": False, "open": "09:00", "close": "17:00"}
                    db_settings["business_hours"] = json.dumps(bh)
                except Exception:
                    pass
            
            updates["settings"] = db_settings

    await tenant_service.update_company(company_id, updates)
    company = await tenant_service.get_company(company_id)
    if not company:
        raise NotFoundError("Company")
    return _fmt_company(company)


@router.post("/{company_id}/logo", summary="Upload company logo")
async def upload_company_logo(
    company_id: str = Path(...),
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require_admin),
):
    """Upload a company logo."""
    MAX_SIZE = 2 * 1024 * 1024  # 2MB
    
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    
    if size > MAX_SIZE:
        raise HTTPException(status_code=400, detail="Logo too large. Maximum size is 2MB.")
        
    allowed_types = ["image/jpeg", "image/png", "image/svg+xml"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Invalid file type. Must be JPG, PNG, or SVG.")

    # Save new file
    filename = file.filename or "logo.png"
    content = await file.read()
    storage_path = await save_upload(company_id=company_id, filename=filename, content=content)
    
    # Delete old logo if exists
    company = await tenant_service.get_company(company_id)
    old_logo = company.get("settings", {}).get("logo_url")
    if old_logo:
        await delete_file(old_logo)

    # Update DB
    db_settings = company.get("settings", {})
    db_settings["logo_url"] = storage_path
    
    await col_companies().update_one(
        {"_id": ObjectId(company_id)},
        {"$set": {"settings": db_settings, "updated_at": datetime.now(timezone.utc)}}
    )
    
    return {"success": True, "logo_url": storage_path}


@router.delete("/{company_id}/logo", summary="Remove company logo")
async def remove_company_logo(
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin),
):
    """Remove company logo."""
    company = await tenant_service.get_company(company_id)
    old_logo = company.get("settings", {}).get("logo_url")
    
    if old_logo:
        await delete_file(old_logo)
        db_settings = company.get("settings", {})
        db_settings["logo_url"] = None
        
        await col_companies().update_one(
            {"_id": ObjectId(company_id)},
            {"$set": {"settings": db_settings, "updated_at": datetime.now(timezone.utc)}}
        )
        
    return {"success": True}

@router.get("/{company_id}/logo", summary="Get company logo")
async def get_company_logo(
    company_id: str = Path(...),
):
    """Public endpoint to fetch the company logo."""
    from fastapi.responses import FileResponse
    company = await tenant_service.get_company(company_id)
    if not company:
        raise NotFoundError("Company")
        
    logo_path = company.get("settings", {}).get("logo_url")
    if not logo_path or not os.path.exists(logo_path):
        raise HTTPException(status_code=404, detail="Logo not found")
        
    return FileResponse(path=logo_path)

@router.get("/{company_id}/overview", summary="Get dashboard overview metrics")
async def get_overview(
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """Aggregate dashboard metrics."""
    usage = await get_usage_summary(company_id)
    
    return {
        "metrics": {
            "total_agents": usage.get("agents_used", 0),
            "active_agents": usage.get("active_agents", 0),
            "total_conversations": usage.get("total_conversations", 0),
            "total_documents": usage.get("kb_docs_used", 0),
            "call_minutes_used": usage.get("call_minutes_used", 0) if usage else 0,
        }
    }


@router.get("/{company_id}/analytics", summary="Get detailed analytics")
async def get_analytics(
    company_id: str = Path(...),
    range: str = "30d",
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """Get detailed time-series and provider analytics for the dashboard."""
    from services.usage_service import get_detailed_analytics
    
    # Parse range (e.g. 7d, 30d, 90d)
    days = 30
    if range and range.endswith("d"):
        try:
            days = int(range[:-1])
        except ValueError:
            pass
            
    analytics_data = await get_detailed_analytics(company_id, days=days)
    return analytics_data



@router.get("/{company_id}/subscription", summary="Get subscription and usage")
async def get_subscription(
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """Get subscription plan, limits, and current month's usage."""
    sub = await tenant_service.get_subscription(company_id)
    usage = await get_usage_summary(company_id)
    return {
        "subscription": {
            "plan": sub.get("plan", "free_trial") if sub else "free_trial",
            "status": sub.get("status", "trial") if sub else "trial",
            "trial_ends_at": sub.get("trial_ends_at") if sub else None,
            "limits": sub.get("limits", {}) if sub else {},
        },
        "usage": usage,
    }


# ── Team Management ───────────────────────────────────────────────────────────

@router.get("/{company_id}/team", summary="List team members")
async def list_team(
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """List all team members with their roles."""
    members = await tenant_service.get_team_members(company_id)
    return {"members": members}


@router.post("/{company_id}/team", status_code=201, summary="Invite team member")
async def invite_member(
    body: TeamMemberCreate,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin),
):
    """Invite a registered user to the company. Admin+ only."""
    result = await tenant_service.invite_team_member(
        company_id=company_id,
        inviter_role=ctx.role,
        email=body.email,
        role=body.role.value,
    )
    return result


@router.patch("/{company_id}/team/{user_id}", summary="Update team member role")
async def update_member_role(
    company_id: str = Path(...),
    user_id: str = Path(...),
    role: str = "member",
    ctx: AuthContext = Depends(require_admin),
):
    """Change a team member's role. Admin+ only."""
    await tenant_service.update_member_role(
        company_id=company_id,
        target_user_id=user_id,
        new_role=role,
        requester_role=ctx.role,
    )
    return {"success": True, "user_id": user_id, "new_role": role}


@router.delete("/{company_id}/team/{user_id}", summary="Remove team member")
async def remove_member(
    company_id: str = Path(...),
    user_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin),
):
    """Remove a team member. Admin+ only."""
    await tenant_service.remove_team_member(
        company_id=company_id,
        target_user_id=user_id,
        requester_role=ctx.role,
    )
    return {"success": True}


@router.patch("/{company_id}/onboarding", summary="Update company during onboarding")
async def update_company_onboarding(
    body: CompanyUpdate,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_onboarding_admin),
):
    """
    Update company settings during onboarding ONLY.
    Does not require email verification.
    """
    # Restrict what can be updated during onboarding
    allowed_keys = {"industry", "country", "settings"}
    updates = {k: v for k, v in body.model_dump().items() if v is not None and k in allowed_keys}
    
    # If they are trying to update settings, ensure it's only onboarding_completed
    if "settings" in updates:
        updates["settings"] = {"onboarding_completed": updates["settings"].get("onboarding_completed", False)}
        
    if updates:
        await tenant_service.update_company(company_id, updates)
        
    company = await tenant_service.get_company(company_id)
    if not company:
        raise NotFoundError("Company")
    return _fmt_company(company)
