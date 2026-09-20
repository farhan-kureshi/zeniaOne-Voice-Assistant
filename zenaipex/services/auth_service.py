"""
Zenaipex AI — Authentication service.

Handles user registration, login, token refresh, email verification,
and password reset flows. All database writes are async (Motor).
"""
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from bson import ObjectId
import logging

from core.database import col_users, col_team_members, col_companies, col_subscriptions
from core.security import (
    hash_password, verify_password,
    create_access_token, create_refresh_token,
    create_email_verification_token, verify_email_token,
    create_password_reset_token, verify_password_reset_token,
)
from core.config import settings
from core.exceptions import (
    ConflictError, InvalidCredentialsError, NotFoundError,
    ValidationError, EmailNotVerifiedError, TenantSuspendedError
)
from models.subscription import PLAN_LIMITS
from slugify import slugify
from services.email_service import send_verification_email

logger = logging.getLogger(__name__)


async def register_user(
    email: str,
    password: str,
    name: str,
    company_name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Register a new platform user and optionally create their first company.

    If company_name is provided:
    - Creates the user
    - Creates the company
    - Creates a team_member entry (role=owner)
    - Creates a free_trial subscription

    Returns:
        Dict with "user", "company" (if created), "access_token", "refresh_token"
    """
    # Check email uniqueness
    existing = await col_users().find_one({"email": email.lower()})
    if existing:
        raise ConflictError("An account with this email already exists")

    # Hash password
    password_hash = hash_password(password)

    # Development/testing convenience only. Production requires real email verification.
    is_auto_verified = settings.app_env in ("development", "testing")
    if is_auto_verified:
        logger.info(f"Auto-verifying development account: {email}")

    # Create user document
    now = datetime.now(timezone.utc)
    user_doc = {
        "email": email.lower(),
        "password_hash": password_hash,
        "name": name,
        "avatar_url": None,
        "is_verified": is_auto_verified,
        "is_platform_admin": False,
        "created_at": now,
        "updated_at": now,
        "last_login_at": None,
    }
    result = await col_users().insert_one(user_doc)
    user_id = str(result.inserted_id)
    user_doc["_id"] = result.inserted_id

    company_doc = None

    # Create company + membership + subscription if company_name provided
    if company_name:
        slug = slugify(company_name, max_length=60)

        # Ensure slug uniqueness (append timestamp suffix if conflict)
        if await col_companies().find_one({"slug": slug}):
            slug = f"{slug}-{int(now.timestamp())}"

        company_doc = {
            "name": company_name,
            "slug": slug,
            "industry": None,
            "country": "IN",
            "timezone": "Asia/Kolkata",
            "plan": "free_trial",
            "is_active": True,
            "settings": {"onboarding_completed": False},
            "created_at": now,
            "updated_at": now,
        }
        company_result = await col_companies().insert_one(company_doc)
        company_id = str(company_result.inserted_id)
        company_doc["_id"] = company_result.inserted_id

        # Create owner membership
        await col_team_members().insert_one({
            "company_id": company_id,
            "user_id": user_id,
            "role": "owner",
            "joined_at": now,
        })

        # Create free trial subscription
        trial_end = now + timedelta(days=settings.free_trial_days)
        limits = PLAN_LIMITS["free_trial"]
        await col_subscriptions().insert_one({
            "company_id": company_id,
            "plan": "free_trial",
            "status": "trial",
            "trial_starts_at": now,
            "trial_ends_at": trial_end,
            "limits": limits,
            "billing_cycle": "monthly",
            "created_at": now,
            "updated_at": now,
        })
        logger.info(f"✅ Company created: {company_name} ({company_id})")

    # Generate tokens
    access_token = create_access_token({"sub": user_id})
    refresh_token = create_refresh_token(user_id)

    # Generate email verification token
    verify_token = create_email_verification_token(email.lower())
    
    # Try sending the email, if it fails we still return the user but log it
    try:
        await send_verification_email(email.lower(), verify_token)
    except Exception as e:
        logger.error(f"Failed to send welcome email to {email}: {e}")

    logger.info(f"✅ User registered: {email} ({user_id})")

    return {
        "user_id": user_id,
        "user": user_doc,
        "company": company_doc,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "email_verify_token": verify_token,  # Keep returning for debugging or tests
    }


async def login_user(email: str, password: str) -> Dict[str, Any]:
    """
    Authenticate user and return tokens.

    Returns:
        Dict with access_token, refresh_token, user doc

    Raises:
        InvalidCredentialsError if email/password don't match
    """
    user = await col_users().find_one({"email": email.lower()})
    if not user:
        raise InvalidCredentialsError()

    if not verify_password(password, user.get("password_hash", "")):
        raise InvalidCredentialsError()

    user_id = str(user["_id"])

    # Enforce Company Suspension Check
    if not user.get("is_platform_admin", False):
        memberships = await col_team_members().find({"user_id": user_id}).to_list(length=100)
        if memberships:
            company_ids = [ObjectId(m["company_id"]) for m in memberships]
            companies = await col_companies().find({"_id": {"$in": company_ids}}).to_list(length=100)
            
            # If they belong to companies, check if ALL are suspended
            if companies:
                all_suspended = all(not c.get("is_active", True) for c in companies)
                if all_suspended:
                    raise TenantSuspendedError()

    # Update last_login_at
    now = datetime.now(timezone.utc)
    await col_users().update_one(
        {"_id": user["_id"]},
        {"$set": {"last_login_at": now}}
    )
    user["last_login_at"] = now

    access_token = create_access_token({"sub": user_id})
    refresh_token = create_refresh_token(user_id)

    logger.info(f"✅ Login: {email}")

    return {
        "user_id": user_id,
        "user": user,
        "access_token": access_token,
        "refresh_token": refresh_token,
    }


async def refresh_access_token(refresh_token: str) -> Dict[str, str]:
    """
    Issue a new access token given a valid refresh token.

    Returns:
        Dict with new access_token

    Raises:
        NotAuthenticatedError if token is invalid/expired
    """
    from core.security import decode_refresh_token
    from core.exceptions import NotAuthenticatedError

    user_id = decode_refresh_token(refresh_token)
    if not user_id:
        raise NotAuthenticatedError("Invalid or expired refresh token")

    # Verify user still exists
    user = await col_users().find_one({"_id": ObjectId(user_id)})
    if not user:
        raise NotAuthenticatedError("User not found")

    new_access_token = create_access_token({"sub": user_id})
    return {"access_token": new_access_token}


async def verify_email(token: str) -> bool:
    """
    Mark user's email as verified using the email verification token.

    Returns:
        True on success
    """
    email = verify_email_token(token)
    if not email:
        raise ValidationError("Invalid or expired email verification link")

    result = await col_users().update_one(
        {"email": email},
        {"$set": {"is_verified": True, "updated_at": datetime.now(timezone.utc)}}
    )
    return result.modified_count > 0


async def resend_verification_email(user_id: str) -> bool:
    """Generate a new token and send the verification email."""
    user = await col_users().find_one({"_id": ObjectId(user_id)})
    if not user:
        raise NotFoundError("User not found")
        
    if user.get("is_verified"):
        raise ConflictError("Email is already verified")
        
    email = user["email"]
    verify_token = create_email_verification_token(email)
    
    # Let the error propagate up so the API can return 500 if SMTP fails
    await send_verification_email(email, verify_token)
    return True


async def request_password_reset(email: str) -> Optional[str]:
    """
    Generate a password reset token for the user.

    Returns:
        Reset token string (caller sends it via email), or None if user not found.
        NOTE: We return None silently (don't reveal if email exists) for security.
    """
    user = await col_users().find_one({"email": email.lower()})
    if not user:
        return None
    user_id = str(user["_id"])
    return create_password_reset_token(user_id)


async def reset_password(token: str, new_password: str) -> bool:
    """
    Reset password using the reset token.

    Returns:
        True on success
    """
    user_id = verify_password_reset_token(token)
    if not user_id:
        raise ValidationError("Invalid or expired password reset link")

    new_hash = hash_password(new_password)
    result = await col_users().update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"password_hash": new_hash, "updated_at": datetime.now(timezone.utc)}}
    )
    return result.modified_count > 0


async def change_password(user_id: str, current_password: str, new_password: str) -> bool:
    """Change password when user knows their current password."""
    user = await col_users().find_one({"_id": ObjectId(user_id)})
    if not user:
        raise NotFoundError("User")

    if not verify_password(current_password, user.get("password_hash", "")):
        raise InvalidCredentialsError()

    new_hash = hash_password(new_password)
    await col_users().update_one(
        {"_id": ObjectId(user_id)},
        {"$set": {"password_hash": new_hash, "updated_at": datetime.now(timezone.utc)}}
    )
    return True
