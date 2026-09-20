"""
Zenaipex AI — AI Agent model.

An Agent is the core AI configuration entity. Each agent defines:
- The AI persona (system prompt)
- Language and voice settings
- Knowledge base association
- LLM configuration
- Greeting/goodbye messages per language

Multiple agents can belong to one company (e.g., "Inbound Receptionist",
"Appointment Reminder Bot", "Support Agent").
"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum
from slugify import slugify

class SalesConfig(BaseModel):
    sales_enabled: bool = False
    sales_agent_id: Optional[str] = None
    default_language: str = "en-IN"
    allowed_call_hours: str = "09:00-18:00"
    call_timeout: int = 45
    max_call_duration: int = 3600
    recording_enabled: bool = True
    transcription_enabled: bool = True
    followup_enabled: bool = True



class AgentStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DRAFT = "draft"


class AgentCreate(BaseModel):
    """Fields to create a new AI agent."""
    name: str = Field(..., min_length=2, max_length=100,
                      description="Human-readable name, e.g. 'Reception Bot'")
    slug: Optional[str] = Field(default=None, max_length=60)
    description: Optional[str] = Field(default=None, max_length=500)
    agent_type: str = Field(default="company_customer_agent", description="Role boundary: platform_admin or company_customer_agent")

    # AI Persona
    system_prompt: str = Field(
        ..., min_length=10, max_length=8000,
        description="The LLM system prompt that defines the agent's persona, rules, and behavior"
    )

    # Language & Voice
    default_language: str = Field(default="en-IN",
                                   description="BCP-47 language code, e.g. 'ta-IN', 'en-IN'")
    supported_languages: List[str] = Field(
        default_factory=lambda: ["en-IN"],
        description="Languages this agent can respond in"
    )
    tts_voice: str = Field(default="anushka",
                           description="Sarvam TTS speaker name")
    tts_model: str = Field(default="bulbul:v3")

    # LLM
    llm_model: str = Field(default="sarvam-105b")
    llm_max_tokens: int = Field(default=1200, ge=100, le=4096)
    llm_temperature: float = Field(default=0.3, ge=0.0, le=2.0)

    # Greeting/Goodbye messages per language
    greeting_messages: Dict[str, str] = Field(
        default_factory=dict,
        description="Per-language greeting text. e.g. {'en-IN': 'Hello!', 'ta-IN': 'வணக்கம்!'}"
    )
    goodbye_messages: Dict[str, str] = Field(
        default_factory=dict,
        description="Per-language goodbye text"
    )

    # Knowledge Base
    knowledge_base_id: Optional[str] = Field(
        default=None,
        description="MongoDB _id of the KnowledgeBase to use for RAG"
    )

    # Call settings
    max_conversation_turns: int = Field(default=20, ge=1, le=100)
    silence_timeout_ms: int = Field(default=800, ge=200, le=5000)
    force_process_timeout_sec: float = Field(default=8.0, ge=3.0, le=30.0)
    enable_background_audio: bool = Field(default=True)

    sales_config: Optional[SalesConfig] = Field(default_factory=SalesConfig)

    # Status
    status: AgentStatus = AgentStatus.DRAFT

    @field_validator("slug", mode="before")
    @classmethod
    def auto_slug(cls, v, info):
        if not v:
            name = info.data.get("name", "")
            return slugify(name, max_length=60)
        return slugify(v, max_length=60)

    @field_validator("supported_languages", mode="before")
    @classmethod
    def ensure_default_in_supported(cls, v, info):
        default = info.data.get("default_language", "en-IN")
        if default not in v:
            v.append(default)
        return v


class AgentUpdate(BaseModel):
    """Mutable agent fields."""
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    default_language: Optional[str] = None
    supported_languages: Optional[List[str]] = None
    tts_voice: Optional[str] = None
    tts_model: Optional[str] = None
    llm_model: Optional[str] = None
    llm_max_tokens: Optional[int] = None
    llm_temperature: Optional[float] = None
    greeting_messages: Optional[Dict[str, str]] = None
    goodbye_messages: Optional[Dict[str, str]] = None
    knowledge_base_id: Optional[str] = None
    max_conversation_turns: Optional[int] = None
    silence_timeout_ms: Optional[int] = None
    force_process_timeout_sec: Optional[float] = None
    enable_background_audio: Optional[bool] = None
    status: Optional[AgentStatus] = None
    sales_config: Optional[SalesConfig] = None


class Agent(BaseModel):
    """Full agent document (as stored in MongoDB)."""
    id: str
    company_id: str
    name: str
    slug: str
    description: Optional[str] = None
    system_prompt: str
    default_language: str = "en-IN"
    supported_languages: List[str] = Field(default_factory=lambda: ["en-IN"])
    tts_voice: str = "anushka"
    tts_model: str = "bulbul:v3"
    llm_model: str = "sarvam-105b"
    llm_max_tokens: int = 1200
    llm_temperature: float = 0.3
    greeting_messages: Dict[str, str] = Field(default_factory=dict)
    goodbye_messages: Dict[str, str] = Field(default_factory=dict)
    knowledge_base_id: Optional[str] = None
    max_conversation_turns: int = 20
    silence_timeout_ms: int = 800
    force_process_timeout_sec: float = 8.0
    enable_background_audio: bool = True
    status: AgentStatus = AgentStatus.DRAFT
    created_at: datetime
    updated_at: datetime

    def get_greeting(self, language: str) -> str:
        """Return greeting for given language, falling back to default."""
        return (
            self.greeting_messages.get(language)
            or self.greeting_messages.get(self.default_language)
            or "Hello! How can I help you today?"
        )

    def get_goodbye(self, language: str) -> str:
        """Return goodbye for given language, falling back to default."""
        return (
            self.goodbye_messages.get(language)
            or self.goodbye_messages.get(self.default_language)
            or "Thank you for calling. Goodbye!"
        )

    class Config:
        use_enum_values = True


class AgentResponse(BaseModel):
    """API response for an agent (excludes internal IDs not needed by client)."""
    id: str
    company_id: str
    name: str
    slug: str
    description: Optional[str] = None
    system_prompt: str
    default_language: str
    supported_languages: List[str]
    tts_voice: str
    llm_model: str
    greeting_messages: Dict[str, str]
    goodbye_messages: Dict[str, str]
    knowledge_base_id: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
