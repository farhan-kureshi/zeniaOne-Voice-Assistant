"""
Zenaipex AI — AI Provider model.

Super Admin global configuration for LLM providers (Sarvam, Gemini, Groq).
"""
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AIProviderCreate(BaseModel):
    provider: str = Field(..., description="E.g., sarvam, gemini, groq")
    enabled: bool = False
    priority: int = 0
    api_key: str
    model: str


class AIProviderUpdate(BaseModel):
    enabled: Optional[bool] = None
    priority: Optional[int] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class AIProvider(BaseModel):
    """Full provider document (as stored in MongoDB)."""
    id: str
    provider: str
    enabled: bool = False
    priority: int = 0
    api_key: str  # Encrypted at rest
    model: str
    updated_at: datetime
    updated_by: str


class AIProviderResponse(BaseModel):
    """Safe response model, masks the API key."""
    id: str
    provider: str
    enabled: bool
    priority: int
    model: str
    updated_at: datetime
    updated_by: str
    has_api_key: bool = True
