"""
Zenaipex AI — Platform-level configuration.

This module loads ONLY platform-level settings (infra secrets, API keys,
JWT config). NO company-specific data lives here — that all lives in MongoDB.
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field
from typing import Optional
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

class Settings(BaseSettings):
    """Platform configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=os.path.join(BASE_DIR, ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Platform Identity ──────────────────────────────────────────────────────
    app_name: str = Field(default="Zenaipex AI")
    app_env: str = Field(default="development")
    app_base_url: str = Field(default="http://localhost:8000")
    frontend_url: str = Field(default="http://localhost:3000")
    app_secret_key: str = Field(default="CHANGE_ME_IN_PRODUCTION_64_chars_minimum")

    # ── MongoDB ────────────────────────────────────────────────────────────────
    mongodb_uri: str = Field(default="")
    mongodb_db_name: str = Field(default="zenaipex")

    # ── Pinecone ───────────────────────────────────────────────────────────────
    pinecone_api_key: str = Field(default="")
    pinecone_index_name: str = Field(default="zenaipex-knowledge")
    pinecone_dimension: int = Field(default=384)
    pinecone_region: str = Field(default="us-east-1")
    pinecone_cloud: str = Field(default="aws")

    # ── Embedding ─────────────────────────────────────────────────────────────
    embedding_model: str = Field(default="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
    embedding_dimension: int = Field(default=384)

    # ── LLM Provider Abstraction ──────────────────────────────────────────────
    llm_provider: str = Field(default="sarvam") # sarvam, gemini, groq
    
    # ── Sarvam AI (platform-shared) ────────────────────────────────────────────
    sarvam_api_key: str = Field(default="")
    sarvam_api_url: str = Field(default="https://api.sarvam.ai")
    sarvam_stt_model: str = Field(default="saarika:v2.5")
    sarvam_tts_model: str = Field(default="bulbul:v3")
    sarvam_llm_model: str = Field(default="sarvam-105b-conversations")
    sarvam_stt_ws_url: str = Field(default="wss://api.sarvam.ai/speech-to-text/ws")
    sarvam_tts_ws_url: str = Field(default="wss://api.sarvam.ai/text-to-speech/ws")

    # ── Google Gemini ──────────────────────────────────────────────────────────
    gemini_api_key: str = Field(default="")
    gemini_model: str = Field(default="gemini-3.6-flash")
    
    # ── Groq ───────────────────────────────────────────────────────────────────
    groq_api_key: str = Field(default="")
    groq_model: str = Field(default="llama3-8b-8192")

    # ── NVIDIA NIM ─────────────────────────────────────────────────────────────
    nvidia_api_key_1: str = Field(default="")
    nvidia_model_1: str = Field(default="nvidia/nemotron-3.5-lightning-30b-a3b")
    nvidia_base_url_1: str = Field(default="https://integrate.api.nvidia.com/v1")

    nvidia_api_key_2: str = Field(default="")
    nvidia_model_2: str = Field(default="deepseek-ai/deepseek-v4-flash-0731")
    nvidia_base_url_2: str = Field(default="https://integrate.api.nvidia.com/v1")

    # ── Twilio (platform-shared, per-company in Phase 3) ──────────────────────
    twilio_account_sid: str = Field(default="")
    twilio_auth_token: str = Field(default="")
    twilio_default_phone_number: str = Field(default="")

    # ── Webhook URLs ───────────────────────────────────────────────────────────
    platform_webhook_base_url: str = Field(default="")

    # ── JWT ───────────────────────────────────────────────────────────────────
    jwt_algorithm: str = Field(default="HS256")
    jwt_access_token_expire_minutes: int = Field(default=60 * 24 * 30)  # 30 days persistent login
    jwt_refresh_token_expire_days: int = Field(default=30)

    # ── Encryption ────────────────────────────────────────────────────────────
    encryption_key: str = Field(default="")

    # ── Email ─────────────────────────────────────────────────────────────────
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    from_email: str = Field(default="noreply@zenaipex.ai")

    # ── Voice Limits ──────────────────────────────────────────────────────────
    voice_history_window_size: int = Field(default=12)

    # ── Plan Limits ───────────────────────────────────────────────────────────
    free_trial_call_minutes: int = Field(default=60)
    free_trial_agents: int = Field(default=1)
    free_trial_kb_docs: int = Field(default=10)
    free_trial_days: int = Field(default=14)

    starter_call_minutes: int = Field(default=500)
    starter_agents: int = Field(default=3)
    starter_kb_docs: int = Field(default=100)

    pro_call_minutes: int = Field(default=2000)
    pro_agents: int = Field(default=10)
    pro_kb_docs: int = Field(default=1000)

    enterprise_call_minutes: int = Field(default=999999)
    enterprise_agents: int = Field(default=999999)
    enterprise_kb_docs: int = Field(default=999999)

    # ── Development / Testing Flags ───────────────────────────────────────────
    ai_billing_enforcement: bool = Field(default=False, description="Set to True to enforce AI billing limits and paywalls.")


    @property
    def is_production(self) -> bool:
        prod = self.app_env == "production"
        if prod and self.app_secret_key == "CHANGE_ME_IN_PRODUCTION_64_chars_minimum":
            raise ValueError("❌ APP_SECRET_KEY must be overridden in production!")
        return prod

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"

    def get_plan_limits(self, plan: str) -> dict:
        """Return resource limits for a given subscription plan."""
        plans = {
            "free_trial": {
                "call_minutes": self.free_trial_call_minutes,
                "agents": self.free_trial_agents,
                "kb_docs": self.free_trial_kb_docs,
            },
            "starter": {
                "call_minutes": self.starter_call_minutes,
                "agents": self.starter_agents,
                "kb_docs": self.starter_kb_docs,
            },
            "professional": {
                "call_minutes": self.pro_call_minutes,
                "agents": self.pro_agents,
                "kb_docs": self.pro_kb_docs,
            },
            "enterprise": {
                "call_minutes": self.enterprise_call_minutes,
                "agents": self.enterprise_agents,
                "kb_docs": self.enterprise_kb_docs,
            },
        }
        return plans.get(plan, plans["free_trial"])


# Singleton instance
settings = Settings()
