"""
Zenaipex AI — Platform User model.

Users are cross-company (one person can be a member of multiple companies).
The user↔company relationship lives in the team_members collection.
"""
from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from datetime import datetime


class UserCreate(BaseModel):
    """Fields for new user registration."""
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=2, max_length=100)
    # For signup flow — creates a company simultaneously
    company_name: Optional[str] = Field(default=None, min_length=2, max_length=100)


class UserLogin(BaseModel):
    """Login credentials."""
    email: EmailStr
    password: str


class UserUpdate(BaseModel):
    """User-editable profile fields."""
    name: Optional[str] = Field(default=None, min_length=2, max_length=100)
    avatar_url: Optional[str] = None


class UserPasswordChange(BaseModel):
    """Password change payload."""
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class UserPasswordReset(BaseModel):
    """Password reset with token."""
    token: str
    new_password: str = Field(..., min_length=8, max_length=128)


class User(BaseModel):
    """Full user document (as stored in MongoDB, password_hash excluded from responses)."""
    id: str
    email: str
    name: str
    avatar_url: Optional[str] = None
    is_verified: bool = False
    is_platform_admin: bool = False  # Zenaipex staff — can see all tenants
    created_at: datetime
    updated_at: datetime
    last_login_at: Optional[datetime] = None


class UserResponse(BaseModel):
    """Safe user response — no password hash, no internal flags."""
    id: str
    email: str
    name: str
    avatar_url: Optional[str] = None
    is_verified: bool
    created_at: datetime


class TokenResponse(BaseModel):
    """Auth token response returned after login or refresh."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int          # access token lifetime in seconds
    user: UserResponse


class RefreshTokenRequest(BaseModel):
    refresh_token: str
