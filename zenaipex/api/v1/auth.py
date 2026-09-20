"""
Zenaipex AI — Auth API router.

POST /api/v1/auth/register     Register + create company
POST /api/v1/auth/login        Authenticate, return tokens
POST /api/v1/auth/refresh      Refresh access token
POST /api/v1/auth/verify-email Verify email address
POST /api/v1/auth/forgot-password  Request password reset
POST /api/v1/auth/reset-password   Reset password with token
POST /api/v1/auth/change-password  Change password (authenticated)
GET  /api/v1/auth/me           Return current user profile
"""
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import EmailStr
from bson import ObjectId

from core.dependencies import get_current_user, get_verified_user
from core.config import settings
from models.user import (
    UserCreate, UserLogin, UserUpdate, UserPasswordChange,
    UserPasswordReset, RefreshTokenRequest, TokenResponse,
)
from services import auth_service

router = APIRouter(prefix="/auth", tags=["Authentication"])


def _format_user(user_doc: dict) -> dict:
    return {
        "id": str(user_doc["_id"]),
        "email": user_doc["email"],
        "name": user_doc.get("name", ""),
        "avatar_url": user_doc.get("avatar_url"),
        "is_verified": user_doc.get("is_verified", False),
        "is_platform_admin": user_doc.get("is_platform_admin", False),
        "created_at": user_doc.get("created_at"),
    }


@router.post("/register", status_code=201, summary="Register a new account")
async def register(body: UserCreate):
    """
    Create a new user account.

    If `company_name` is provided, also creates the company and sets
    up a Free Trial subscription. The user becomes the company Owner.

    Returns JWT access + refresh tokens immediately (no email gate at login).
    """
    result = await auth_service.register_user(
        email=body.email,
        password=body.password,
        name=body.name,
        company_name=body.company_name,
    )
    response = {
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "user": _format_user(result["user"]),
    }
    if result.get("company"):
        company = result["company"]
        response["company"] = {
            "id": str(company["_id"]),
            "name": company["name"],
            "slug": company["slug"],
            "plan": company.get("plan", "free_trial"),
        }
    return response


@router.post("/login", summary="Login and get tokens")
async def login(body: UserLogin):
    """Authenticate with email/password. Returns JWT tokens."""
    result = await auth_service.login_user(
        email=body.email,
        password=body.password,
    )
    return {
        "access_token": result["access_token"],
        "refresh_token": result["refresh_token"],
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
        "user": _format_user(result["user"]),
    }


@router.post("/refresh", summary="Refresh access token")
async def refresh_token(body: RefreshTokenRequest):
    """Exchange a refresh token for a new access token."""
    result = await auth_service.refresh_access_token(body.refresh_token)
    return {
        "access_token": result["access_token"],
        "token_type": "bearer",
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


@router.post("/verify-email", summary="Verify email address")
async def verify_email(token: str):
    """Verify email with the token sent in the verification email."""
    success = await auth_service.verify_email(token)
    return {"verified": success, "message": "Email verified successfully" if success else "Verification failed"}


@router.post("/resend-verification", summary="Resend verification email")
async def resend_verification(user: dict = Depends(get_current_user)):
    """Resend the verification email for the current user."""
    try:
        await auth_service.resend_verification_email(str(user["_id"]))
        return {"success": True, "message": "Verification email sent"}
    except Exception as e:
        # If it's a known exception like ConflictError it will be handled by exception handlers
        # But if it's an SMTP error, we want to expose a clean 500 error
        from fastapi import HTTPException
        from core.exceptions import DomainError
        if isinstance(e, DomainError):
            raise e
        raise HTTPException(status_code=503, detail=str(e))


@router.post("/forgot-password", summary="Request password reset email")
async def forgot_password(email: EmailStr):
    """
    Request a password reset link for the given email.
    Always returns 200 (don't reveal if email exists).
    """
    token = await auth_service.request_password_reset(email)
    # In production: send email with token
    # For now, return token in response (dev only)
    return {"message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password", summary="Reset password with token")
async def reset_password(body: UserPasswordReset):
    """Reset password using the token from the reset email."""
    success = await auth_service.reset_password(body.token, body.new_password)
    return {"success": success, "message": "Password reset successfully" if success else "Reset failed"}


@router.post("/change-password", summary="Change password (authenticated)")
async def change_password(
    body: UserPasswordChange,
    user: dict = Depends(get_current_user),
):
    """Change password when user knows their current password."""
    user_id = str(user["_id"])
    await auth_service.change_password(user_id, body.current_password, body.new_password)
    return {"success": True, "message": "Password changed successfully"}


@router.get("/me", summary="Get current user profile")
async def get_me(user: dict = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    # Development-only auto-activation for the current test user
    if settings.app_env in ("development", "testing") and not user.get("is_verified"):
        from core.database import col_users
        await col_users().update_one({"_id": user["_id"]}, {"$set": {"is_verified": True}})
        user["is_verified"] = True

    return _format_user(user)


@router.patch("/me", summary="Update user profile")
async def update_me(
    body: UserUpdate,
    user: dict = Depends(get_current_user),
):
    """Update name or avatar_url."""
    from datetime import datetime, timezone
    from core.database import col_users
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    updates["updated_at"] = datetime.now(timezone.utc)
    await col_users().update_one({"_id": user["_id"]}, {"$set": updates})
    updated = {**user, **updates}
    return _format_user(updated)
