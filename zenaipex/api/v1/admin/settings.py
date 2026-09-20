from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import os
from datetime import datetime, timezone
from fastapi.responses import FileResponse

from core.dependencies import get_platform_admin
from core.database import col_platform_settings, col_activity_logs
from services.storage_service import save_upload, delete_file

router = APIRouter(prefix="/settings", tags=["Admin - Settings"])
public_router = APIRouter(prefix="/settings", tags=["Admin - Settings Public"])

# ── Models ────────────────────────────────────────────────────────────────────

class PlatformSettingsUpdate(BaseModel):
    platform_name: Optional[str] = None
    default_language: Optional[str] = None
    default_timezone: Optional[str] = None

class AIDefaultsUpdate(BaseModel):
    default_provider: Optional[str] = None
    default_model: Optional[str] = None
    default_token_limit: Optional[int] = None
    default_temperature: Optional[float] = None

class SecuritySettingsUpdate(BaseModel):
    session_timeout_minutes: Optional[int] = None
    require_strong_passwords: Optional[bool] = None

class NotificationSettingsUpdate(BaseModel):
    admin_notifications_enabled: Optional[bool] = None
    system_alerts_enabled: Optional[bool] = None
    security_alerts_enabled: Optional[bool] = None

class SystemSettingsUpdate(BaseModel):
    maintenance_mode: Optional[bool] = None
    maintenance_message: Optional[str] = None

class PricingSettingsUpdate(BaseModel):
    input_1m: Optional[float] = None
    output_1m: Optional[float] = None

class SettingsUpdateBody(BaseModel):
    platform: Optional[PlatformSettingsUpdate] = None
    ai_defaults: Optional[AIDefaultsUpdate] = None
    security: Optional[SecuritySettingsUpdate] = None
    notifications: Optional[NotificationSettingsUpdate] = None
    system: Optional[SystemSettingsUpdate] = None
    pricing: Optional[Dict[str, PricingSettingsUpdate]] = None


# Default settings factory
def get_default_settings() -> Dict[str, Any]:
    return {
        "type": "global",
        "platform": {
            "platform_name": "Zenaipex AI",
            "default_language": "en",
            "default_timezone": "UTC",
            "logo_path": None,
        },
        "ai_defaults": {
            "default_provider": "sarvam",
            "default_model": "sarvam-105b",
            "default_token_limit": 1024,
            "default_temperature": 0.7,
        },
        "security": {
            "session_timeout_minutes": 60,
            "require_strong_passwords": True,
        },
        "notifications": {
            "admin_notifications_enabled": True,
            "system_alerts_enabled": True,
            "security_alerts_enabled": True,
        },
        "system": {
            "maintenance_mode": False,
            "maintenance_message": "System is currently undergoing maintenance. Please try again later.",
        },
        "pricing": {},
        "updated_at": datetime.now(timezone.utc)
    }

async def fetch_or_create_settings() -> Dict[str, Any]:
    doc = await col_platform_settings().find_one({"type": "global"})
    if not doc:
        doc = get_default_settings()
        await col_platform_settings().insert_one(doc)
    doc["_id"] = str(doc["_id"])
    return doc

# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def get_settings(user: dict = Depends(get_platform_admin)):
    """Get all platform settings."""
    doc = await fetch_or_create_settings()
    # Mask actual path out of API response, indicate presence instead
    if doc.get("platform", {}).get("logo_path"):
        doc["platform"]["has_logo"] = True
    else:
        doc["platform"]["has_logo"] = False
        
    # Inject backend environment overrides for the UI
    from core.config import settings as app_settings
    doc["env_overrides"] = {
        "ai_billing_enforcement": app_settings.ai_billing_enforcement
    }
    
    return {"settings": doc}


@router.put("")
async def update_settings(
    body: SettingsUpdateBody,
    user: dict = Depends(get_platform_admin)
):
    """Update sections of platform settings."""
    current = await fetch_or_create_settings()
    
    update_data = {}
    updated_sections = []
    
    if body.platform:
        for k, v in body.platform.model_dump(exclude_unset=True).items():
            update_data[f"platform.{k}"] = v
        updated_sections.append("Platform")
            
    if body.ai_defaults:
        for k, v in body.ai_defaults.model_dump(exclude_unset=True).items():
            update_data[f"ai_defaults.{k}"] = v
        updated_sections.append("AI Defaults")
            
    if body.security:
        for k, v in body.security.model_dump(exclude_unset=True).items():
            update_data[f"security.{k}"] = v
        updated_sections.append("Security")
            
    if body.notifications:
        for k, v in body.notifications.model_dump(exclude_unset=True).items():
            update_data[f"notifications.{k}"] = v
        updated_sections.append("Notifications")
            
    if body.system:
        for k, v in body.system.model_dump(exclude_unset=True).items():
            update_data[f"system.{k}"] = v
        updated_sections.append("System")
        
    if body.pricing is not None:
        # For a dict of models, replace the whole dict
        pricing_data = {k: v.model_dump(exclude_unset=True) for k, v in body.pricing.items()}
        update_data["pricing"] = pricing_data
        updated_sections.append("Pricing")

    if not update_data:
        # Just return the current settings without modified flags if nothing to update
        doc = await fetch_or_create_settings()
        if doc.get("platform", {}).get("logo_path"):
            doc["platform"]["has_logo"] = True
        return {"success": True, "settings": doc}

    update_data["updated_at"] = datetime.now(timezone.utc)
    
    await col_platform_settings().update_one(
        {"type": "global"},
        {"$set": update_data}
    )
    
    # Log activity
    await col_activity_logs().insert_one({
        "actor_name": user.get("name", "Admin"),
        "actor_email": user.get("email"),
        "action": "settings_updated",
        "target": ", ".join(updated_sections),
        "details": f"Updated global settings sections: {', '.join(updated_sections)}",
        "created_at": datetime.now(timezone.utc)
    })
    
    doc = await fetch_or_create_settings()
    if doc.get("platform", {}).get("logo_path"):
        doc["platform"]["has_logo"] = True
    return {"success": True, "settings": doc}


@router.post("/logo")
async def upload_logo(
    file: UploadFile = File(...),
    user: dict = Depends(get_platform_admin)
):
    """Upload a platform logo."""
    content_bytes = await file.read()
    
    if len(content_bytes) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Logo too large. Maximum size is 2MB.")

    content_type = file.content_type or "image/png"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Unsupported file type. Must be an image.")

    filename = file.filename or "logo.png"
    storage_path = await save_upload("platform", filename, content_bytes)
    
    current = await fetch_or_create_settings()
    old_logo = current.get("platform", {}).get("logo_path")
    
    await col_platform_settings().update_one(
        {"type": "global"},
        {"$set": {"platform.logo_path": storage_path, "updated_at": datetime.now(timezone.utc)}}
    )
    
    if old_logo:
        await delete_file(old_logo)
        
    await col_activity_logs().insert_one({
        "actor_name": user.get("name", "Admin"),
        "actor_email": user.get("email"),
        "action": "settings_updated",
        "target": "Platform Logo",
        "details": "Uploaded a new platform logo",
        "created_at": datetime.now(timezone.utc)
    })

    return {"success": True}

@router.delete("/logo")
async def remove_logo(user: dict = Depends(get_platform_admin)):
    """Remove platform logo."""
    current = await fetch_or_create_settings()
    old_logo = current.get("platform", {}).get("logo_path")
    
    if old_logo:
        await delete_file(old_logo)
        await col_platform_settings().update_one(
            {"type": "global"},
            {"$set": {"platform.logo_path": None, "updated_at": datetime.now(timezone.utc)}}
        )
        
        await col_activity_logs().insert_one({
            "actor_name": user.get("name", "Admin"),
            "actor_email": user.get("email"),
            "action": "settings_updated",
            "target": "Platform Logo",
            "details": "Removed platform logo",
            "created_at": datetime.now(timezone.utc)
        })
        
    return {"success": True}

@public_router.get("/public")
async def get_public_settings():
    """Public endpoint to fetch basic branding settings for login/sidebar."""
    doc = await col_platform_settings().find_one({"type": "global"})
    if not doc:
        return {"platform_name": "ZeniaAI", "has_logo": False}
        
    has_logo = bool(doc.get("platform", {}).get("logo_path"))
    platform_name = doc.get("platform", {}).get("platform_name", "ZeniaAI")
    
    return {
        "platform_name": platform_name,
        "has_logo": has_logo
    }

@public_router.get("/logo")
async def get_logo():
    """Public endpoint to fetch the logo."""
    # We do not require auth here so the login page could potentially show it,
    # or the app can just use it without complex auth headers in <img>.
    # Note: depends on your security posture, but a logo is usually public.
    
    doc = await col_platform_settings().find_one({"type": "global"})
    if not doc:
        raise HTTPException(status_code=404, detail="No settings found")
        
    logo_path = doc.get("platform", {}).get("logo_path")
    if not logo_path or not os.path.exists(logo_path):
        raise HTTPException(status_code=404, detail="Logo not found")
        
    return FileResponse(path=logo_path)
