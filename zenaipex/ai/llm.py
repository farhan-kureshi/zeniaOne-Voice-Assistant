"""
Zenaipex AI — Multi-tenant LLM client.

Per-agent parameterization: system_prompt, model, temperature, and
language are all loaded from the Agent document at call time.
No hardcoded defaults — all come from the DB.

This is the MULTI-TENANT replacement for modules/llm_client.py.
"""
import asyncio
import aiohttp
import time
import logging
import json
from typing import List, Dict, Any, Optional, AsyncGenerator, Tuple

from core.config import settings

logger = logging.getLogger(__name__)

def format_business_hours(bh_str: str) -> str:
    if not bh_str: return ""
    try:
        data = json.loads(bh_str)
        if not isinstance(data, dict): return bh_str
        lines = []
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        for day in days:
            if day in data:
                day_data = data[day]
                if day_data.get('isOpen'):
                    open_t = day_data.get('openTime') or day_data.get('open') or ''
                    close_t = day_data.get('closeTime') or day_data.get('close') or ''
                    lines.append(f"- {day.capitalize()}: {open_t} - {close_t}")
                else:
                    lines.append(f"- {day.capitalize()}: Closed")
        holidays = data.get('holidays', [])
        if holidays:
            lines.append("Holidays/Special Closures:")
            for h in holidays:
                lines.append(f"- {h.get('name', 'Holiday')} on {h.get('date', '')}")
        return "\n".join(lines) if lines else bh_str
    except Exception:
        return bh_str

# --- Provider Health & Cooldown Tracking ---
_provider_health: Dict[str, Dict[str, Any]] = {}
# Track last successful provider per config context (company_id + agent_id + stage)
_config_success_history: Dict[str, str] = {}

def get_config_key(company_id: Optional[str], agent_id: Optional[str], stage: str) -> str:
    return f"{company_id or 'default'}_{agent_id or 'default'}_{stage}"

def get_last_successful_provider(company_id: Optional[str], agent_id: Optional[str], stage: str) -> Optional[str]:
    return _config_success_history.get(get_config_key(company_id, agent_id, stage))

def is_provider_healthy(provider_name: str, allow_degraded: bool = False) -> bool:
    if allow_degraded:
        return True
        
    health = _provider_health.get(provider_name)
    if not health:
        return True
    
    state = health.get("circuit_state", "HEALTHY")
    if state == "OPEN":
        # Check if we can transition to HALF_OPEN
        if time.time() >= health.get("cooldown_until", 0):
            health["circuit_state"] = "HALF_OPEN"
            logger.info(f"[PROVIDER_PROBE] provider={provider_name} state=HALF_OPEN probe=true recovered=false")
            return True
        return False
        
    # Strictly enforce 429 rate limit cooldowns unless degraded
    reason = health.get("last_failure_reason", "")
    if reason == "429_rate_limit" and time.time() < health.get("cooldown_until", 0):
        return False
        
    return True

def record_provider_success(provider_name: str, company_id: Optional[str] = None, agent_id: Optional[str] = None, stage: str = "generation", latency: float = 0.0):
    if provider_name not in _provider_health:
        _provider_health[provider_name] = {"successes": 0, "failures": 0, "timeouts": 0, "429s": 0, "avg_latency": 0.0, "consecutive_failures": 0, "circuit_state": "HEALTHY"}
        
    health = _provider_health[provider_name]
    
    if health.get("circuit_state") in ["OPEN", "HALF_OPEN", "DEGRADED"] or health.get("consecutive_failures", 0) > 0:
        logger.info(f"[PROVIDER_RECOVERY] provider={provider_name} state=HEALTHY recovered=true prev_failures={health.get('consecutive_failures', 0)}")
        
    health["successes"] = health.get("successes", 0) + 1
    health["consecutive_failures"] = 0
    health["circuit_state"] = "HEALTHY"
    health["cooldown_until"] = 0
    health["last_success"] = time.time()
    
    # Running average latency
    prev_avg = health.get("avg_latency", 0.0)
    if prev_avg == 0.0:
        health["avg_latency"] = latency
    else:
        health["avg_latency"] = (prev_avg * 0.8) + (latency * 0.2)
    
    config_key = get_config_key(company_id, agent_id, stage)
    _config_success_history[config_key] = provider_name

def record_provider_failure(provider_name: str, reason: str = "error"):
    if provider_name not in _provider_health:
        _provider_health[provider_name] = {"successes": 0, "failures": 0, "timeouts": 0, "429s": 0, "avg_latency": 0.0, "consecutive_failures": 0, "circuit_state": "HEALTHY"}
        
    health = _provider_health[provider_name]
    health["failures"] = health.get("failures", 0) + 1
    health["consecutive_failures"] = health.get("consecutive_failures", 0) + 1
    
    if "timeout" in reason.lower():
        health["timeouts"] = health.get("timeouts", 0) + 1
        
    health["last_failure"] = time.time()
    health["last_failure_reason"] = reason
    
    # Fast circuit break for billing / credit exhaustion (HTTP 402)
    if "402" in str(reason) or "credit" in str(reason).lower() or "payment" in str(reason).lower():
        health["circuit_state"] = "OPEN"
        health["cooldown_until"] = time.time() + 86400  # 24 hours cooldown for exhausted credits
        logger.warning(f"CIRCUIT BREAKER OPEN for {provider_name} due to exhausted credits ({reason}). Skipping for 24h.")
        return

    # Circuit Breaker Logic
    consecutive = health["consecutive_failures"]
    if consecutive >= 3:
        health["circuit_state"] = "OPEN"
        health["cooldown_until"] = time.time() + 60 # Escalated backoff
        logger.warning(f"CIRCUIT BREAKER OPEN for {provider_name} due to {consecutive} consecutive failures.")
    else:
        health["circuit_state"] = "DEGRADED"
        health["cooldown_until"] = time.time() + 30

def record_provider_429(provider_name: str, retry_after_sec: int = 45):
    if provider_name not in _provider_health:
        _provider_health[provider_name] = {"successes": 0, "failures": 0, "timeouts": 0, "429s": 0, "avg_latency": 0.0, "consecutive_failures": 0, "circuit_state": "HEALTHY"}
    
    # Enforce a minimum backoff for 429s to prevent instant retry loops if header is 0
    actual_retry_sec = max(int(retry_after_sec), 30)
    
    health = _provider_health[provider_name]
    health["429s"] = health.get("429s", 0) + 1
    health["consecutive_failures"] = health.get("consecutive_failures", 0) + 1
    health["last_failure"] = time.time()
    health["last_failure_reason"] = "429_rate_limit"
    
    consecutive = health["consecutive_failures"]
    if consecutive >= 3:
        health["circuit_state"] = "OPEN"
        health["cooldown_until"] = time.time() + max(actual_retry_sec, 60)
    else:
        health["circuit_state"] = "DEGRADED"
        health["cooldown_until"] = time.time() + actual_retry_sec

def _build_user_lang_reminder(lang_result) -> str:
    """
    Build a compact one-line language reminder to append to the user message.
    Keeps the reminder short so it doesn't inflate token cost.
    """
    script = lang_result.script
    lang = lang_result.lang
    native_scripts = {
        "devanagari", "gujarati_script", "bengali", "gurmukhi",
        "tamil", "telugu", "kannada", "malayalam", "odia", "arabic_urdu",
    }
    if script in native_scripts:
        script_label = {
            "devanagari":      "Hindi Devanagari script",
            "gujarati_script": "Gujarati script",
            "bengali":         "Bengali script",
            "gurmukhi":        "Punjabi Gurmukhi script",
            "tamil":           "Tamil script",
            "telugu":          "Telugu script",
            "kannada":         "Kannada script",
            "malayalam":       "Malayalam script",
            "odia":            "Odia script",
            "arabic_urdu":     "Urdu script",
        }.get(script, f"{lang} native script")
        return f"{script_label} only. Do NOT use Roman letters."
    # Romanized
    return (
        f"Roman/Latin {lang.title()} only. "
        f"Do NOT switch to English, do NOT use {lang.title()} native script. "
        f"Keep English technical terms (API names, product names) as-is."
    )

def get_prioritized_providers(providers: List[Any], company_id: Optional[str], agent_id: Optional[str], stage: str) -> List[Any]:
    """
    Sort providers intelligently based on:
    1. Circuit State (Skip OPEN)
    2. Cooldown
    3. Last successful affinity (by stage)
    4. Average Latency
    5. Fallbacks
    """
    if stage in ["intent", "rewrite"]:
        providers = [p for p in providers if "sarvam" not in p.provider.lower()]

    last_success = get_last_successful_provider(company_id, agent_id, stage)
    
    def score_provider(p) -> tuple:
        p_name = p.provider.lower()
        health = _provider_health.get(p_name, {})
        
        # 1. State: OPEN = worst, DEGRADED = bad, HEALTHY/HALF_OPEN = good
        state = health.get("circuit_state", "HEALTHY")
        is_open = 1 if state == "OPEN" else 0
        state_score = 0 if state in ["HEALTHY", "HALF_OPEN"] else (1 if state == "DEGRADED" else 2)
        
        # 2. Cooldown
        is_cooldown = 1 if time.time() < health.get("cooldown_until", 0) else 0
        
        # 3. Affinity
        affinity = 0 if p_name == last_success else 1
        
        # 4. Latency
        latency = health.get("avg_latency", 99.0)
        
        # Lower score is better
        score = (is_open, is_cooldown, affinity, state_score, latency)
        print(f"DEBUG score_provider: {p_name} stage={stage} score={score}")
        return score
        
    sorted_providers = sorted(providers, key=score_provider)
    return sorted_providers


class AgentLLMClient:
    """
    Async LLM client configured per-agent.

    All parameters come from the Agent document loaded at call start:
    - model, max_tokens, temperature → agent.llm_model, etc.
    - system_prompt → agent.system_prompt
    - api_key → platform settings.sarvam_api_key (or company override in Phase 3)

    Usage:
        agent = await load_agent_for_call(phone_number)
        async with await AgentLLMClient.create(agent["agent"]) as llm:
            # Non-streaming
            response = await llm.generate(user_message, conversation_history)

            # Streaming (SSE tokens)
            async for token in llm.stream(messages):
                ...
    """

    def __init__(
        self,
        system_prompt: str,
        providers: List[Any],
        max_tokens: int = 1200,
        temperature: float = 0.3,
        top_p: float = 0.95,
        agent_type: str = "company_customer_agent",
        company_profile: str = "",
        company_name: str = "",
        company_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        request_id: str = "REQ-UNKNOWN",
        tts_voice: str = "ritu",
    ):
        self.system_prompt = system_prompt
        self.providers = providers
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.top_p = top_p
        self.agent_type = agent_type
        self.company_profile = company_profile
        self.company_name = company_name
        self.company_id = company_id
        self.agent_id = agent_id
        self.request_id = request_id
        self.tts_voice = tts_voice
        self._session: Optional[aiohttp.ClientSession] = None
        self.current_budget_deadline: Optional[float] = None

    def set_budget(self, seconds: float = 10.0):
        """Set a global deadline across all subsequent operations (intent, rewrite, generation)."""
        import time
        self.current_budget_deadline = time.perf_counter() + seconds

    @classmethod
    async def create(cls, agent_doc: Dict[str, Any], request_id: str = "REQ-UNKNOWN") -> "AgentLLMClient":
        """
        Construct an LLM client from an Agent MongoDB document asynchronously.
        
        Uses provider_service to fetch the active DB-configured LLM providers.
        """
        from services.provider_service import resolve_providers
        from core.database import col_companies
        from bson import ObjectId
        
        company_id = agent_doc.get("company_id")
        company_profile = ""
        company = None
        if company_id:
            company = await col_companies().find_one({"_id": ObjectId(company_id)})
            if company:
                profile_lines = []
                if company.get("name"): profile_lines.append(f"Company Name: {company['name']}")
                if company.get("industry"): profile_lines.append(f"Industry: {company['industry']}")
                if company.get("country"): profile_lines.append(f"Location/Country: {company['country']}")
                if company.get("description"): profile_lines.append(f"About/Description: {company['description']}")
                if company.get("website"): profile_lines.append(f"Website: {company['website']}")
                settings = company.get("settings", {})
                if settings.get("business_hours"): 
                    formatted_bh = format_business_hours(settings['business_hours'])
                    profile_lines.append(f"Business Hours:\n{formatted_bh}")
                if settings.get("phone"): profile_lines.append(f"Phone: {settings['phone']}")
                if settings.get("business_email"): profile_lines.append(f"Email: {settings['business_email']}")
                if settings.get("address"): profile_lines.append(f"Address: {settings['address']}")
                if profile_lines:
                    company_profile = "\n".join(profile_lines)
        
        providers = await resolve_providers()
        
        # Re-order providers based on agent's requested llm_model
        agent_model = agent_doc.get("llm_model", "")
        preferred_provider = None
        if agent_model and providers:
            if "gemini" in agent_model.lower():
                preferred_provider = "gemini"
            elif "llama" in agent_model.lower() or "mixtral" in agent_model.lower() or "gemma" in agent_model.lower():
                preferred_provider = "groq"
            elif "sarvam" in agent_model.lower():
                preferred_provider = "sarvam"
            elif "nvidia" in agent_model.lower() or "nemotron" in agent_model.lower():
                preferred_provider = "nvidia_1"

        # Global strict priority: Groq (ultra-fast <0.5s) -> Gemini -> NVIDIA 1 -> NVIDIA 2 -> Sarvam
        priority_map = {
            "groq": 1,
            "gemini": 2,
            "nvidia": 3,
            "nvidia_1": 3,
            "nvidia_2": 4,
            "sarvam": 5
        }
        
        # Sort all providers according to the strict priority map
        providers.sort(key=lambda p: priority_map.get(p.provider.lower(), 99))
        
        # If agent explicitly requested a model, pull its provider to the front ONLY if healthy
        if preferred_provider and is_provider_healthy(preferred_provider):
            for i, p in enumerate(providers):
                if preferred_provider in p.provider.lower():
                    preferred_p = providers.pop(i)
                    preferred_p.model = agent_model # Override default model
                    providers.insert(0, preferred_p)
                    break
                    
        # Deduplicate by provider family to prevent cascading timeouts (e.g. nvidia -> nvidia_2)
        # unless it was explicitly pulled to the front.
        seen_families = set()
        deduped_providers = []
        for p in providers:
            # Example: 'nvidia_2' -> 'nvidia'
            family = p.provider.lower().split('_')[0]
            if family not in seen_families:
                seen_families.add(family)
                deduped_providers.append(p)
                
        providers = deduped_providers


        return cls(
            system_prompt=agent_doc["system_prompt"],
            providers=providers,
            max_tokens=agent_doc.get("llm_max_tokens", 1200),
            temperature=agent_doc.get("llm_temperature", 0.3),
            agent_type=agent_doc.get("agent_type", "company_customer_agent"),
            company_profile=company_profile,
            company_name=(
                agent_doc.get("name", "").replace(" Agent", "").strip() or company.get("name", "")
            ) if company and company.get("name") == "ZeniaAI Internal Workspace" and agent_doc.get("agent_type") != "platform_admin" else (company.get("name", "") if 'company' in locals() and company else ""),
            company_id=company_id,
            agent_id=str(agent_doc.get("_id")) if agent_doc.get("_id") else None,
            request_id=request_id,
            tts_voice=agent_doc.get("tts_voice", "ritu"),
        )

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create reusable aiohttp session."""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(limit=10, keepalive_timeout=30)
            # Reduced from 90/60 to shorter aggressive bounds for fast-failing voice mode
            timeout = aiohttp.ClientTimeout(total=20, connect=5, sock_read=15)
            self._session = aiohttp.ClientSession(connector=connector, timeout=timeout)
            logger.info(f"[{self.request_id}] [LLM_SESSION_CREATE]\nsession_id={id(self._session)}")
        return self._session

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    async def _build_messages(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]],
        context_docs: Optional[List[Dict[str, Any]]] = None,
        language: str = "en-IN",
        current_date: Optional[str] = None,
        company_name: Optional[str] = None,
        intent: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """
        Build the messages array for the LLM API call.
        """
        from ai.language_detector import detect_language

        # Detect the user's language + script before building the prompt
        lang_result = detect_language(user_message, conversation_history)

        # Explicit language preference enforcement
        if language in ["hinglish", "hi-IN", "hindi_latin"]:
            lang_result.lang = "hindi"
            lang_result.script = "latin"
            lang_result.style_instruction = (
                "LANGUAGE & STYLE RULE (CRITICAL - HIGHEST PRIORITY):\n"
                "The user is speaking in Hinglish. You MUST respond in conversational Romanized Hinglish (using English/Latin letters ONLY, e.g., 'Main theek hoon! Aap bataiye aap kaise hain?').\n"
                "Do NOT write in Devanagari Hindi script. Do NOT use pure English. Use natural, daily-spoken Hinglish words written in English letters."
            )
        elif language in ["gujarati", "gu-IN"]:
            lang_result.lang = "gujarati"
            lang_result.script = "gujarati_script"
        elif language in ["english", "en-US"]:
            lang_result.lang = "english"
            lang_result.script = "latin"

        system_content = self.system_prompt
        
        # Enforce response quality & formatting guidance
        system_content += """

CRITICAL ASSISTANT DIRECTIVES:
1. Professional Formatting & Quality: Respond like a senior, knowledgeable AI assistant (such as ChatGPT or Gemini). Be highly articulate, helpful, and professional.
2. Structure & Emojis: ALWAYS structure your answers cleanly. Use bullet points for multiple items, bold text for emphasis, and sprinkle relevant professional emojis (e.g., 🚀, 💡, 📊, ✅) to make the text engaging and easy to read.
3. Comprehensive Information: When the user asks about features, capabilities, or documents, explain key points clearly and thoroughly based on available document context, using lists if applicable.
4. Proactive Suggestions: Always conclude by proactively suggesting 2-3 specific follow-up questions the user can ask. You MUST format these strictly as a bulleted list of questions at the very end of your response. Example:
   - What are the core features?
   - How do I set up a custom domain?
5. Phonetic & Brand Awareness: Note that the user may pronounce "ZeniaOne" as "Zinnia One", "Janya One", or "Zenia". Always treat these as referring to ZeniaOne."""

        # Enforce GENDER & PERSONA consistency
        voice_key = (getattr(self, "tts_voice", None) or "ritu").lower()
        MALE_VOICES = {"rohan", "rahul", "aditya", "kabir", "amit", "dev", "varun", "sumit", "arjun", "ashutosh", "ratan", "manan", "aayan", "shubh", "advait", "anand", "tarun", "sunny", "mani", "gokul", "vijay", "mohit", "rehan", "soham"}
        is_male = voice_key in MALE_VOICES

        if is_male:
            system_content += """

GENDER & GRAMMAR DIRECTIVE (MALE PERSONA):
- You are a MALE AI Assistant.
- In Hindi / Hinglish, you MUST strictly use masculine verbs, adjectives, and self-references when speaking about yourself:
  * Say 'Main aapki madad kar sakta hoon' (NEVER 'sakti hoon').
  * Say 'Main sun raha hoon' (NEVER 'rahi hoon').
  * Say 'Main aapko guide karunga' (NEVER 'karungi').
  * Refer to yourself as 'Main aapka assistant hoon' (masculine)."""
        else:
            system_content += """

GENDER & GRAMMAR DIRECTIVE (FEMALE PERSONA):
- You are a FEMALE AI Assistant.
- In Hindi / Hinglish, you MUST strictly use feminine verbs, adjectives, and self-references when speaking about yourself:
  * Say 'Main aapki madad kar sakti hoon' (NEVER 'sakta hoon').
  * Say 'Main sun rahi hoon' (NEVER 'raha hoon').
  * Say 'Main aapko guide karungi' (NEVER 'karunga').
  * Refer to yourself as 'Main aapki assistant hoon' (feminine)."""

        # Ensure company name is correctly mapped before substitution
        if company_name and company_name.upper() == "INTERNAL / PLATFORM":
            company_name = "ZeniaOne"

        # Substitute template variables in system prompt
        if current_date:
            system_content = system_content.replace("{current_date}", current_date)
        if company_name:
            system_content = system_content.replace("{company_name}", company_name)

        # Legacy language placeholder (kept for backward-compat with old prompts)
        lang_names = {
            "en-IN": "English", "ta-IN": "Tamil", "hi-IN": "Hindi",
            "te-IN": "Telugu", "kn-IN": "Kannada", "ml-IN": "Malayalam",
        }
        lang_name = lang_names.get(language, "English")
        system_content = system_content.replace("{user_language}", lang_name)
        
        # Inject Company Profile
        if self.company_profile:
            system_content += f"\n\n🏢 COMPANY PROFILE:\n{self.company_profile}\n"

        if getattr(self, "company_name", "").upper() == "INTERNAL / PLATFORM" or getattr(self, "company_name", "") == "ZeniaOne":
            system_content += """
🏢 AUTHORITATIVE PRODUCT IDENTITY:
Product 1: 
Name: ZeniaOne
Type: Primary platform/product
Description: The core AI voice agent platform.

Product 2:
Name: ZeniaHR
Type: HRMS / HR product
Description: The human resources management product that handles policies, payroll, and attendance.

* Use this authoritative identity when answering questions like "What is ZeniaOne?" or "What is ZeniaHR?".
"""

        # Ensure company context
        company_name = getattr(self, "company_name", None) or "our company"
        company_id = getattr(self, "company_id", None)
        
        if company_name.upper() == "INTERNAL / PLATFORM":
            company_name = "ZeniaOne"
        
        # Override identity if customer-facing agent was created in the admin workspace
        if company_name == "ZeniaAI Internal Workspace" and getattr(self, "agent_type", "company_customer_agent") != "platform_admin":
            from core.database import col_agents
            from bson import ObjectId
            agent_id = getattr(self, "agent_id", None)
            if agent_id:
                agent = await col_agents().find_one({"_id": ObjectId(agent_id)})
                if agent:
                    company_name = agent.get("name", "").replace(" Agent", "").strip() or company_name
                    self.company_name = company_name

        # Extract dynamic topics from company knowledge base
        available_topics = set()
        
        # 1. Topic Discovery via Company Documents
        if company_id:
            from core.database import col_documents
            try:
                # Load up to 50 active documents for the current company
                docs_cursor = col_documents().find({"company_id": company_id, "status": "ready"}).limit(50)
                async for d in docs_cursor:
                    if d.get("filename"):
                        # Convert filename to a clean topic name (e.g. "Pulse Circle Guide.pdf" -> "Pulse Circle Guide")
                        name = d["filename"].rsplit('.', 1)[0].replace('_', ' ').replace('-', ' ').strip().title()
                        if name:
                            available_topics.add(name)
            except Exception:
                pass

        # 2. Topic Discovery via Retrieved Context
        if context_docs:
            for doc in context_docs:
                meta = doc.get("metadata", {})
                
                # STRICT TENANT ISOLATION: Guarantee chunk metadata belongs to the current authorized tenant
                doc_company = str(meta.get("company_id", ""))
                doc_namespace = str(meta.get("namespace", ""))
                
                if company_id:
                    if doc_company and doc_company != str(company_id):
                        continue
                    if doc_namespace and doc_namespace != str(company_id):
                        continue
                        
                if meta.get("section"): available_topics.add(str(meta.get("section")).strip().title())
                if meta.get("title"): available_topics.add(str(meta.get("title")).strip().title())

        # Inject RAG context
        if context_docs:
            context_text = "\n\n".join([
                f"--- Snippet {i+1} ---\n{doc.get('text', '')}"
                for i, doc in enumerate(context_docs[:8])
            ])
            system_content += f"\n\n📚 DETAILED KNOWLEDGE BASE CONTEXT:\n{context_text}\n\n"
            if available_topics:
                topics_str = ", ".join(sorted(list(available_topics))[:15])
                system_content += f"AVAILABLE KNOWLEDGE TOPICS (Do not expose this list directly, but use it to answer what information you can provide): {topics_str}\n\n"
        else:
            system_content += f"\n\n📚 DETAILED KNOWLEDGE BASE CONTEXT:\n[No additional context available for this query.]\n\n"

        # Inject strict grounding and quality rules
        if getattr(self, "agent_type", "company_customer_agent") != "platform_admin":
            system_content += (
                "CRITICAL RULES FOR PROFESSIONAL AI RESPONSES:\n"
                f"1. IDENTITY: You are a professional, friendly representative of {company_name or 'the company'}. Your job is to help customers understand the company based ONLY on available knowledge.\n"
                "   a) NEVER introduce yourself as an internal system, AI, ZeniaAI assistant, platform manager, or bot.\n"
                "   b) Speak naturally. Avoid robotic phrases like 'I assist with platform management' or 'How can I assist you today?'.\n"
                "   c) If the user asks 'what do you work', 'what can you do', or 'konsi information de sakteho', DO NOT list generic AI capabilities. Naturally mention that you can provide information about the company/project (like the AVAILABLE KNOWLEDGE TOPICS if provided).\n"
                "   d) Do NOT claim the company has products, services, pricing, etc., unless those are explicitly in the trusted context/topics.\n"
                "   e) Do NOT ask 'which system' if the user explicitly named the company previously. Resolve it automatically.\n"
                "   f) STRICT IDENTITY PROTECTION: NEVER mention ChatGPT, OpenAI, Gemini, Google, Llama, or Groq. If asked who created you or what model you are, you MUST say you are an AI representative for the company.\n"
                "2. STRICT KNOWLEDGE PRIORITY & NO HALLUCINATION:\n"
                "   a) FINAL ANSWER MUST BE STRICTLY SUPPORTED BY AVAILABLE TRUSTED CONTEXT.\n"
                "   b) FIRST, use the DETAILED KNOWLEDGE BASE CONTEXT provided above. SECOND, use the COMPANY PROFILE.\n"
                "   c) If the user asks what the company does, its business activity, or on what 'basis' it works, use the COMPANY PROFILE's About/Description to explain its core operations.\n"
                "   d) THIRD, use Conversation History ONLY for resolving references (e.g. 'it'). NEVER use general world knowledge to fill missing company/project facts.\n"
                "   e) Do not invent: phone numbers, physical addresses, office locations, email addresses, business hours, features, technologies, frameworks, databases, APIs, users, developers, dates, revenue, pricing, statistics, capabilities, authentication methods, architecture, workflows, business information, project objectives, scope, or future features unless supported by trusted retrieved context.\n"
                "   f) CONTACT DETAILS & ADDRESS STRICT RULE: If the user asks for business hours, phone number, email, or physical address, and it is NOT explicitly present in the COMPANY PROFILE or retrieved context, you MUST explicitly state that this information is not configured or currently unavailable. NEVER invent fake street addresses (like '123 Main Street'), fake cities, or dummy phone numbers!\n"
                "   g) Do not 'complete' an answer using assumptions, even if plausible or common for similar systems. A statement can be plausible and still must be omitted if the source does not support it.\n"
                "3. ANSWER ONLY WHAT THE QUESTION REQUIRES:\n"
                "   a) Answer the exact question asked. Do not automatically dump every fact available in the context.\n"
                "   b) If asked about 'technologies', use ONLY the 'Technology Used' section. Do not add unrelated authentication or frontend details unless specifically asked.\n"
                "   c) If asked about 'database' or 'admin panel', answer ONLY what is documented for that specific topic. Do NOT add unrelated info.\n"
                "   d) For broad questions ('What is RitHan?', 'Tell me about RitHan.'), synthesize ONLY the most relevant supported facts (what it is, main purpose, major documented features, core technologies). Do NOT make up a polished company profile from scattered hints.\n"
                "   e) If only part of the question is supported, answer only the supported part. Do not invent the rest.\n"
                "4. PRESERVE SOURCE TERMINOLOGY & AVOID MARKETING FLUFF:\n"
                "   a) When the documentation provides a specific term, prefer that terminology.\n"
                "   b) Do not upgrade simple source wording into marketing language.\n"
                "   c) Avoid unnecessary words like: advanced, cutting-edge, powerful, sophisticated, revolutionary, secure, real-time, smart, intelligent unless the source explicitly supports the claim.\n"
                "5. EVIDENCE HANDLING & SOURCE CONFLICTS:\n"
                "   a) Do NOT combine unrelated chunks into one broad answer simply because they were retrieved.\n"
                "   b) If multiple retrieved chunks contain different wording, prefer the more direct and specific source for the question. Do not invent a reconciliation. Say only what is clearly supported.\n"
                "6. GROUNDING & UNKNOWN INFORMATION (STRICT ENFORCEMENT):\n"
                "   a) BEFORE answering, you MUST verify that the context explicitly supports your answer.\n"
                "   b) SPELLING/PHONETIC TYPO HANDLING: If the user asks about an entity (product, person, concept) that is NOT in the context, BUT it sounds phonetically similar or is a minor typo of a KNOWN entity in your context or AVAILABLE TOPICS (e.g., 'zenya HR' instead of 'ZeniaHR', or 'ZeniaOneHR' instead of 'ZeniaOne' or 'ZeniaHR'), do NOT just say you don't know. Instead, politely ask them to confirm if they meant the known entity (e.g., 'Mujhe zenya HR ke baare mein jankari nahi mili. Kya aap ZeniaHR ke baare mein puchna chahte hain?'). DO NOT APPEND SUGGESTED QUESTIONS to this response. Just ask the confirmation question and stop.\n"
                f"   c) If the user asks a factual question about the company/project and the fact is NOT present in trusted context, you MUST NOT guess or invent facts. You MUST answer EXACTLY with the fallback message: '{lang_result.fallback_message}'\n"
                "   d) CASUAL CONVERSATION & LANGUAGE SWITCHING: You are fluent in ALL Indian and global languages (including Marathi, Gujarati, Punjabi, Bengali, Tamil, etc.). If the user is engaging in casual greeting (e.g., 'how are you') or asking about your language capabilities (e.g., 'can you speak marathi', 'gujarati me bat karoge'), DO NOT use the fallback message and DO NOT deny the request. Respond naturally in the requested language, confirm that you can speak it, and ask how you can help them.\n"
                "   e) REPEATED QUESTIONS: Even if the user repeats a question already answered in conversation history, answer it thoroughly and politely from the trusted context without refusing.\n"
                "7. INTERNAL VERIFICATION (SILENT):\n"
                "   a) Before finalizing, mentally verify: Is every factual claim supported? Am I adding plausible sounding but unsupported details? Am I merging chunks unjustifiably? Am I adding marketing fluff?\n"
                "   b) Remove unsupported claims before answering.\n"
                "8. CLEAN OUTPUT: Output ONLY the final customer-facing response. DO NOT output any internal reasoning, thoughts, or <think> tags. DO NOT prefix with 'FINAL_ANSWER:'. DO NOT mention 'retrieved chunks', 'Pinecone', 'RAG', 'namespaces', or filenames.\n"
                "9. DIRECT & CONCISE ANSWER STYLE: Be direct, professional, natural, and concise. Avoid unnecessary repetition, long preambles, and boilerplate like 'Based on the provided context...'. Focus strictly on the asked topic.\n"
                "10. PROFESSIONAL FOLLOW-UP: For informational, product, or company questions, conclude your answer with ONE short, natural professional follow-up question inviting the user to ask more (e.g., 'Would you like to know more about these features?', 'Can I explain any of this in more detail?'). Use the EXACT same language and script as your response. DO NOT add follow-ups to simple greetings, yes/no confirmations, error messages, very short acknowledgements, or when the user is clearly ending the conversation.\n"
                "11. INTERACTIVE SUGGESTIONS: For every informational response, you MUST append a section at the very end with a bulleted list of 1-3 short follow-up questions framed strictly from the USER'S perspective (e.g., '- Tell me about pricing?', '- How do I set this up?'). Do NOT frame these bullets from your perspective.\n"
                "12. PROFESSIONAL FORMATTING & COUNTING:\n"
                "   a) Make your responses visually appealing and 'smart'. Always bold key terms, company names, and product names.\n"
                "   b) Use bullet points and relevant emojis to structure lists and highlight important features (e.g., 🏢, 🚀, 💬, 📊).\n"
                "   c) ACCURATE COUNTING: If you claim 'There are X products' or 'X features', you MUST mathematically verify that you are actually listing exactly X items. Do not miscount.\n"
            )

        # ── LANGUAGE & STYLE RULE (injected last = highest instruction priority) ──
        # This is the output of our deterministic language_detector — it overrides
        # any language instruction that might be buried in the agent system prompt.
        system_content += f"\n\n{lang_result.style_instruction}\n"

        messages = [{"role": "system", "content": system_content}]

        # Step 6: Context history filtering
        # Remove short acknowledgements, greetings, and empty messages to save tokens
        # Keep only substantive Q&A turns
        filtered_history = []
        for msg in conversation_history:
            content = msg.get("content", "").strip().lower()
            if not content:
                continue
            # Filter out pure acknowledgements and greetings
            import re
            if re.match(r"^(ok|okay|thanks|thank\s*you|haan|accha|theek(\s*hai)?|yes|no|hi|hello|namaste|sure)$", content):
                continue
            filtered_history.append(msg)

        # Conversation history (configurable window, default 12 messages = 6 turns)
        from core.config import settings
        window_size = settings.voice_history_window_size
        recent = filtered_history[-window_size:]
        for msg in recent:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", ""),
            })
            
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[VOICE_HISTORY_WINDOW] loaded_messages={len(conversation_history)} used_messages={len(recent)}")

        # ── Critical: also embed the language reminder on the user message itself ──
        # The system prompt injection (above) is necessary but not always sufficient:
        # LLMs can be pulled back toward English by English KB snippets or English
        # history. Adding a compact reminder directly on the user-turn message
        # ensures it is the LAST text the model reads before generating.
        user_msg_with_lang = user_message
        if lang_result.lang != "english":
            # Compact 1-line reminder that won't inflate context length
            lang_reminder = _build_user_lang_reminder(lang_result)
            user_msg_with_lang = f"{user_message}\n\n[RESPOND IN: {lang_reminder}]"

        messages.append({"role": "user", "content": user_msg_with_lang})
        return messages


    async def generate(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        context_docs: Optional[List[Dict[str, Any]]] = None,
        language: str = "en-IN",
        current_date: Optional[str] = None,
        company_name: Optional[str] = None,
        intent: Optional[str] = None,
        stage: str = "generation",
    ) -> Tuple[Optional[str], Dict[str, int]]:
        """Non-streaming LLM call. Returns (content, usage_dict)."""
        messages = await self._build_messages(
            user_message,
            conversation_history or [],
            context_docs,
            language,
            current_date,
            company_name,
            intent,
        )
        from services.usage_service import log_llm_request
        session = await self._get_session()

        # Sort providers dynamically for generation
        gen_providers = get_prioritized_providers(self.providers, getattr(self, "company_id", None), getattr(self, "agent_id", None), stage=stage)
        
        queue_names = " -> ".join([p.provider.lower() for p in gen_providers])
        ctx_chunks = len(context_docs) if context_docs else 0
        logger.info(f"[{self.request_id}] GENERATION START\nProvider Queue: {queue_names}\nContext Chunks: {ctx_chunks}")

        last_error_message = None
        global_start_time = time.perf_counter()
        deadline = getattr(self, "current_budget_deadline", None)
        if not deadline:
            deadline = global_start_time + 20.0

        for i, provider in enumerate(gen_providers):
            # Fast fail if we exceeded global latency budget
            remaining_budget = deadline - time.perf_counter()
            if remaining_budget <= 0.2:
                logger.error(f"[{self.request_id}] GLOBAL GENERATION TIMEOUT EXCEEDED (remaining: {remaining_budget:.2f}s). Aborting failover.")
                break

            p_name = provider.provider.lower()
            
            if not is_provider_healthy(p_name, allow_degraded=(i == len(gen_providers) - 1)):
                fallback_str = gen_providers[i+1].provider.lower() if i+1 < len(gen_providers) else "NONE"
                logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: SKIPPED (COOLDOWN)\nLatency: 0.00s\nFallback: {fallback_str}")
                last_error_message = f"⚠️ Error: LLM provider {p_name} is temporarily skipping requests."
                continue
                
            model = provider.model
            api_key = str(provider.api_key).strip() if provider.api_key else ""
            
            if p_name == "gemini":
                api_url = "https://generativelanguage.googleapis.com/v1beta/openai"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            elif p_name == "groq":
                api_url = "https://api.groq.com/openai/v1"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            elif "nvidia" in p_name:
                api_url = "https://integrate.api.nvidia.com/v1"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            else:
                api_url = "https://api.sarvam.ai/v1"
                headers = {"Content-Type": "application/json", "api-subscription-key": api_key}
                
            endpoint = f"{api_url}/chat/completions"
            p_max_tokens = self.max_tokens
            if "nvidia" in p_name.lower() or "nemotron" in model.lower():
                p_max_tokens = max(self.max_tokens, 2500)
            
            if p_name == "groq" and model in ["mixtral-8x7b-32768"]:
                model = "llama-3.3-70b-versatile"

            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": p_max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p,
            }

            try:
                provider_max = 30 if "nvidia" in p_name.lower() else 12
                
                remaining_providers = len(gen_providers) - i - 1
                actual_timeout = max(3.0, min(provider_max, remaining_budget))
                
                logger.info(f"[BUDGET_TRACE]\nstage=generation\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nactual_timeout={actual_timeout:.2f}\nresult=ATTEMPTING")
                
                req_timeout = aiohttp.ClientTimeout(total=actual_timeout, connect=3, sock_read=actual_timeout)
                
                start = time.perf_counter()
                async with session.post(endpoint, json=payload, headers=headers, timeout=req_timeout) as resp:
                    elapsed = time.perf_counter() - start
                    if resp.status != 200:
                        err = await resp.text()
                        status_str = f"429_QUOTA" if resp.status == 429 else f"HTTP_{resp.status}"
                        fallback_str = gen_providers[i+1].provider.lower() if i+1 < len(gen_providers) else "NONE"
                        logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: {status_str}\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                        logger.info(f"[BUDGET_TRACE]\nstage=generation\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nactual_timeout={actual_timeout:.2f}\nresult={status_str}")
                        
                        if resp.status == 429:
                            last_error_message = f"⚠️ Error: AI Quota Exceeded (429) on {p_name}. Please check your billing or rate limits."
                            retry_after = int(resp.headers.get("Retry-After", 45))
                            record_provider_429(p_name, retry_after)
                        elif resp.status in (400, 401, 403, 404):
                            # Do not poison global provider health for tenant-specific auth errors or bad request structures
                            # Just fail over immediately without circuit breaker penalty
                            last_error_message = f"⚠️ Error: LLM provider {p_name} configuration error ({resp.status})."
                        else:
                            last_error_message = f"⚠️ Error: LLM provider {p_name} failed ({resp.status})."
                            record_provider_failure(p_name, f"HTTP_{resp.status}")
                            
                        if self.company_id:
                            await log_llm_request(
                                company_id=self.company_id,
                                agent_id=self.agent_id,
                                provider=p_name,
                                model=model,
                                latency_ms=elapsed * 1000,
                                success=False,
                                error_msg=f"HTTP {resp.status}: {err[:100]}",
                                direction="generate",
                                request_id=self.request_id
                            )
                        continue
                        
                    result = await resp.json()
                    
                    if "choices" not in result or not result["choices"]:
                        fallback_str = gen_providers[i+1].provider.lower() if i+1 < len(gen_providers) else "NONE"
                        logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: EMPTY_RESPONSE\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                        last_error_message = f"⚠️ Error: LLM provider {p_name} returned no choices."
                        if self.company_id:
                            await log_llm_request(
                                company_id=self.company_id,
                                agent_id=self.agent_id,
                                provider=p_name,
                                model=model,
                                latency_ms=elapsed * 1000,
                                success=False,
                                error_msg="No choices in response",
                                direction="generate",
                                request_id=self.request_id
                            )
                        continue
                        
                    msg = result["choices"][0].get("message", {})
                    content = msg.get("content")
                        
                    if not content or not str(content).strip():
                        fallback_str = gen_providers[i+1].provider.lower() if i+1 < len(gen_providers) else "NONE"
                        logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: EMPTY_RESPONSE\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                        last_error_message = f"⚠️ Error: LLM provider {p_name} returned empty content."
                        record_provider_failure(p_name)
                        if self.company_id:
                            await log_llm_request(
                                company_id=self.company_id,
                                agent_id=self.agent_id,
                                provider=p_name,
                                model=model,
                                latency_ms=elapsed * 1000,
                                success=False,
                                error_msg="Empty content in response",
                                direction="generate",
                                request_id=self.request_id
                            )
                        continue
                        
                    content_str = str(content)
                    import re
                    
                    # Strip all reasoning block types (fully closed)
                    for tag in ["think", "thinking", "reasoning"]:
                        content_str = re.sub(rf"<{tag}>.*?</{tag}>", "", content_str, flags=re.DOTALL | re.IGNORECASE)
                    
                    # If an unclosed tag remains, the generation was truncated during reasoning.
                    # We strip everything from the tag onwards.
                    for tag in ["<think>", "<thinking>", "<reasoning>"]:
                        if tag in content_str.lower():
                            # Find index case-insensitive
                            idx = content_str.lower().find(tag)
                            if idx != -1:
                                content_str = content_str[:idx]
                    
                    # Strip aggressive system leakage patterns
                    leak_patterns = [
                        r"Let me re-read.*?\n",
                        r"Rule \d+.*?\n",
                        r"I need to check.*?\n",
                        r"I'll combine.*?\n",
                        r"Proceed.*?\n",
                        r"thinking process.*?\n",
                        r"Here's a thinking process.*?\n",
                        r"Let's look at.*?\n",
                        r"Let's formulate.*?\n",
                        r"But wait,.*?\n",
                        r"I should check.*?\n",
                        r"I must follow.*?\n"
                    ]
                    for pattern in leak_patterns:
                        content_str = re.sub(pattern, "", content_str, flags=re.IGNORECASE)
                        
                    # Remove markdown/code-fence wrappers containing reasoning
                    content_str = re.sub(r"```(json|markdown|text)?.*?```", "", content_str, flags=re.DOTALL | re.IGNORECASE)
                    
                    # Extract final answer
                    if "FINAL_ANSWER:" in content_str.upper():
                        # Find the last occurrence or just split by it case-insensitive
                        parts = re.split(r"FINAL_ANSWER:", content_str, flags=re.IGNORECASE)
                        content_str = parts[-1].strip()
                        
                        # If the extracted part still contains obvious reasoning words, it means the model was "thinking" about the final answer.
                        reasoning_leak_words = ["Rule ", "Let's ", "I need to", "I should", "But wait", "Wait,"]
                        if any(rw.lower() in content_str.lower() for rw in reasoning_leak_words):
                            # This is a leaked reasoning block masquerading as a final answer
                            content_str = ""
                    elif "nvidia" in p_name.lower() or "nemotron" in model.lower():
                        # Strict enforcement: if the reasoning model didn't output the final answer boundary,
                        # it means the generation was truncated during reasoning. Treat as failed.
                        content_str = ""
                    else:
                        # For standard models, try basic prefix stripping if they mirrored the prompt
                        for boundary in ["FINAL_ANSWER:", "Final Answer:", "Final Response:", "Answer:", "Response:"]:
                            if content_str.strip().startswith(boundary):
                                content_str = content_str.strip()[len(boundary):]
                                break
                                
                    content_str = content_str.strip().strip('"').strip("'").strip()
                        
                    if not content_str:
                        fallback_str = gen_providers[i+1].provider.lower() if i+1 < len(gen_providers) else "NONE"
                        logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: INVALID_STRUCTURED_OUTPUT\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                        last_error_message = f"⚠️ Error: LLM provider {p_name} returned empty content after stripping reasoning."
                        record_provider_failure(p_name)
                        if self.company_id:
                            await log_llm_request(
                                company_id=self.company_id,
                                agent_id=self.agent_id,
                                provider=p_name,
                                model=model,
                                latency_ms=elapsed * 1000,
                                success=False,
                                error_msg="Empty content after stripping reasoning",
                                direction="generate",
                                request_id=self.request_id
                            )
                        continue

                    usage = result.get("usage", {})
                    
                    if self.company_id:
                        await log_llm_request(
                            company_id=self.company_id,
                            agent_id=self.agent_id,
                            provider=p_name,
                            model=model,
                            input_tokens=usage.get("prompt_tokens", 0),
                            output_tokens=usage.get("completion_tokens", 0),
                            total_tokens=usage.get("total_tokens", 0),
                            latency_ms=elapsed * 1000,
                            success=True,
                            direction="generate",
                                request_id=self.request_id
                            )
                        
                    logger.info(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: SUCCESS\nLatency: {elapsed:.2f}s")
                    record_provider_success(p_name, getattr(self, "company_id", None), getattr(self, "agent_id", None), stage="generation")
                    self.last_provider = p_name
                    self.last_model = model
                    
                    # Log USAGE if available
                    if usage:
                        in_t = usage.get("prompt_tokens", "unavailable")
                        out_t = usage.get("completion_tokens", "unavailable")
                        tot_t = usage.get("total_tokens", "unavailable")
                        logger.info(f"[{self.request_id}] USAGE\nProvider: {p_name}\nStage: generation\nInput Tokens: {in_t}\nOutput Tokens: {out_t}\nTotal Tokens: {tot_t}\nStatus: SUCCESS")
                        
                    return content_str, usage
            except asyncio.TimeoutError:
                elapsed = time.perf_counter() - start
                fallback_str = gen_providers[i+1].provider.lower() if i+1 < len(gen_providers) else "NONE"
                logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: TIMEOUT\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                logger.info(f"[BUDGET_TRACE]\nstage=generation\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nactual_timeout={actual_timeout:.2f}\nresult=TIMEOUT")
                last_error_message = f"⚠️ Error: LLM provider {p_name} timed out."
                record_provider_failure(p_name)
                if self.company_id:
                    await log_llm_request(
                        company_id=self.company_id,
                        agent_id=self.agent_id,
                        provider=p_name,
                        model=model,
                        latency_ms=elapsed * 1000,
                        success=False,
                        error_msg="Timeout on reading data",
                        direction="generate",
                                request_id=self.request_id
                            )
                continue
            except Exception as exc:
                elapsed = time.perf_counter() - start
                fallback_str = gen_providers[i+1].provider.lower() if i+1 < len(gen_providers) else "NONE"
                logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: ERROR\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                logger.info(f"[BUDGET_TRACE]\nstage=generation\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nactual_timeout={actual_timeout:.2f}\nresult=ERROR")
                last_error_message = f"⚠️ Error: LLM provider {p_name} exception: {str(exc)[:100]}"
                record_provider_failure(p_name)
                if self.company_id:
                    await log_llm_request(
                        company_id=self.company_id,
                        agent_id=self.agent_id,
                        provider=p_name,
                        model=model,
                        latency_ms=elapsed * 1000,
                        success=False,
                        error_msg=str(exc)[:100],
                        direction="generate",
                                request_id=self.request_id
                            )
                continue
                
        logger.error(f"[{self.request_id}] GENERATION FAILED\nAll enabled LLM providers failed for generate().")
        # Ensure we never expose internal empty-content errors from reasoning truncation.
        logger.error(f"[{self.request_id}] AI REQUEST FAILED\nAll enabled LLM providers failed for generate.\nLast Error: {last_error_message}")
        return "⚠️ Error: All providers unavailable", {}

    async def stream(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        context_docs: Optional[List[Dict[str, Any]]] = None,
        language: str = "en-IN",
        current_date: Optional[str] = None,
        company_name: Optional[str] = None,
        max_tokens: Optional[int] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming LLM call — yields tokens as they arrive (SSE).
        Used in the real-time voice pipeline for sentence-level TTS.
        """
        messages = await self._build_messages(
            user_message,
            conversation_history or [],
            context_docs,
            language,
            current_date,
            company_name,
        )
        from services.usage_service import log_llm_request
        session = await self._get_session()

        # Sort providers for stream: preferred provider -> last successful generation -> standard
        last_gen_p = get_last_successful_provider(getattr(self, "company_id", None), getattr(self, "agent_id", None), stage="generation")
        stream_providers = self.providers.copy()
        if last_gen_p:
            for idx, p in enumerate(stream_providers):
                if p.provider.lower() == last_gen_p and is_provider_healthy(p.provider.lower()):
                    stream_providers.insert(0, stream_providers.pop(idx))
                    break
        
        queue_names = " -> ".join([p.provider.lower() for p in stream_providers])
        ctx_chunks = len(context_docs) if context_docs else 0
        logger.info(f"[{self.request_id}] GENERATION START (STREAM)\nProvider Queue: {queue_names}\nContext Chunks: {ctx_chunks}")

        last_error_message = None
        global_start_time = time.perf_counter()
        deadline = getattr(self, "current_budget_deadline", None)
        if not deadline:
            deadline = global_start_time + 10.0
        
        for i, provider in enumerate(stream_providers):
            # Fast fail if we exceeded global latency budget
            remaining_budget = deadline - time.perf_counter()
            if remaining_budget <= 0.2:
                logger.error(f"[{self.request_id}] GLOBAL STREAM TIMEOUT EXCEEDED (remaining: {remaining_budget:.2f}s). Aborting failover.")
                break

            p_name = provider.provider.lower()
            
            if not is_provider_healthy(p_name, allow_degraded=(i == len(stream_providers) - 1)):
                # If this is the only provider or the last provider in the fallback chain and we haven't found a healthy one yet, let's just try it anyway.
                if i == len(stream_providers) - 1 and i == 0:
                    pass
                else:
                    fallback_str = stream_providers[i+1].provider.lower() if i+1 < len(stream_providers) else "NONE"
                    logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: SKIPPED (COOLDOWN)\nLatency: 0.00s\nFallback: {fallback_str}")
                    continue
                
            model = provider.model
            api_key = str(provider.api_key).strip() if provider.api_key else ""
            
            if p_name == "gemini":
                api_url = "https://generativelanguage.googleapis.com/v1beta/openai"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            elif p_name == "groq":
                api_url = "https://api.groq.com/openai/v1"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            elif "nvidia" in p_name:
                api_url = "https://integrate.api.nvidia.com/v1"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            else:
                api_url = "https://api.sarvam.ai/v1"
                headers = {"Content-Type": "application/json", "api-subscription-key": api_key}
                
            endpoint = f"{api_url}/chat/completions"
            
            if p_name == "groq" and model in ["mixtral-8x7b-32768", "llama-3.1-70b-versatile", "llama-3.3-70b-versatile", "llama3-8b-8192"]:
                model = "openai/gpt-oss-20b"
                
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens or self.max_tokens,
                "temperature": self.temperature,
                "top_p": getattr(self, "top_p", 0.7),
                "stream": True,
            }

            success = False
            start = time.perf_counter()
            try:
                provider_max = 30 if "nvidia" in p_name.lower() else 8
                
                remaining_providers = len(stream_providers) - i - 1
                reserve = remaining_providers * 1.0
                allocated = remaining_budget - reserve
                
                if allocated < 1.0 and remaining_providers > 0:
                    fallback_str = stream_providers[i+1].provider.lower()
                    logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: SKIPPED (INSUFFICIENT BUDGET, RESERVING FOR FALLBACK)\nLatency: 0.00s\nFallback: {fallback_str}")
                    logger.info(f"[BUDGET_TRACE]\nstage=stream\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nreserve={reserve:.2f}\nallocated={allocated:.2f}\nactual_timeout=0.00\nresult=SKIPPED")
                    continue
                
                if remaining_providers == 0:
                    actual_timeout = min(provider_max, remaining_budget)
                else:
                    actual_timeout = max(1.0, min(provider_max, allocated))
                
                logger.info(f"[BUDGET_TRACE]\nstage=stream\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nreserve={reserve:.2f}\nallocated={allocated:.2f}\nactual_timeout={actual_timeout:.2f}\nresult=ATTEMPTING")
                
                # For stream, connect timeout is 3, read timeout is longer
                req_timeout = aiohttp.ClientTimeout(total=actual_timeout, connect=3, sock_read=actual_timeout)
                async with session.post(endpoint, json=payload, headers=headers, timeout=req_timeout) as resp:
                    elapsed = time.perf_counter() - start
                    if resp.status != 200:
                        err = await resp.text()
                        status_str = f"429_QUOTA" if resp.status == 429 else f"HTTP_{resp.status}"
                        fallback_str = stream_providers[i+1].provider.lower() if i+1 < len(stream_providers) else "NONE"
                        logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: {status_str}\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                        logger.info(f"[BUDGET_TRACE]\nstage=stream\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nreserve={reserve:.2f}\nallocated={allocated:.2f}\nactual_timeout={actual_timeout:.2f}\nresult={status_str}")
                        if resp.status == 429:
                            last_error_message = f"⚠️ Error: AI Quota Exceeded (429) on {p_name}. Please check your billing or rate limits."
                        else:
                            last_error_message = f"⚠️ Error: LLM provider {p_name} failed ({resp.status})."
                        
                        record_provider_failure(p_name)
                        if self.company_id:
                            await log_llm_request(
                                company_id=self.company_id,
                                agent_id=self.agent_id,
                                provider=p_name,
                                model=model,
                                latency_ms=elapsed * 1000,
                                success=False,
                                error_msg=f"HTTP {resp.status}: {err[:100]}",
                                direction="stream",
                                request_id=self.request_id
                            )
                        continue

                    buffer = ""
                    async for chunk in resp.content.iter_any():
                        buffer += chunk.decode("utf-8")
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            line = line.strip()
                            if not line.startswith("data: "):
                                continue
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                import json
                                parsed = json.loads(data)
                                choices = parsed.get("choices", [])
                                if not choices:
                                    continue
                                delta = choices[0].get("delta", {})
                                content = delta.get("content")
                                if content:
                                    success = True
                                    yield str(content)
                            except Exception:
                                continue
                    
                    elapsed = time.perf_counter() - start
                    if success:
                        logger.info(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: SUCCESS\nLatency: {elapsed:.2f}s")
                        record_provider_success(p_name, getattr(self, "company_id", None), getattr(self, "agent_id", None))
                        
                    if success and self.company_id:
                        await log_llm_request(
                            company_id=self.company_id,
                            agent_id=self.agent_id,
                            provider=p_name,
                            model=model,
                            latency_ms=elapsed * 1000,
                            success=True,
                            direction="stream",
                                request_id=self.request_id
                            )
                        return
                    elif not success:
                        record_provider_failure(p_name)
                        if self.company_id:
                            await log_llm_request(
                                company_id=self.company_id,
                                agent_id=self.agent_id,
                                provider=p_name,
                                model=model,
                                latency_ms=elapsed * 1000,
                                success=False,
                                error_msg="No successful content generated in stream",
                                direction="stream",
                                request_id=self.request_id
                            )
            except asyncio.TimeoutError:
                elapsed = time.perf_counter() - start if 'start' in locals() else 0
                fallback_str = stream_providers[i+1].provider.lower() if i+1 < len(stream_providers) else "NONE"
                logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: TIMEOUT\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                logger.info(f"[BUDGET_TRACE]\nstage=stream\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nreserve={reserve:.2f}\nallocated={allocated:.2f}\nactual_timeout={actual_timeout:.2f}\nresult=TIMEOUT")
                last_error_message = f"⚠️ Error: LLM provider {p_name} timed out."
                record_provider_failure(p_name)
                if self.company_id:
                    await log_llm_request(
                        company_id=self.company_id,
                        agent_id=self.agent_id,
                        provider=p_name,
                        model=model,
                        latency_ms=elapsed * 1000,
                        success=False,
                        error_msg="Timeout on reading data",
                        direction="stream",
                                request_id=self.request_id
                            )
                continue
            except Exception as exc:
                elapsed = time.perf_counter() - start if 'start' in locals() else 0
                fallback_str = stream_providers[i+1].provider.lower() if i+1 < len(stream_providers) else "NONE"
                logger.warning(f"[{self.request_id}] GENERATION PROVIDER {p_name}\nStatus: ERROR\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                logger.info(f"[BUDGET_TRACE]\nstage=stream\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nreserve={reserve:.2f}\nallocated={allocated:.2f}\nactual_timeout={actual_timeout:.2f}\nresult=ERROR")
                last_error_message = f"⚠️ Error: LLM provider {p_name} exception: {str(exc)[:100]}"
                record_provider_failure(p_name)
                if self.company_id:
                    await log_llm_request(
                        company_id=self.company_id,
                        agent_id=self.agent_id,
                        provider=p_name,
                        model=model,
                        latency_ms=elapsed * 1000,
                        success=False,
                        error_msg=str(exc)[:100],
                        direction="stream",
                                request_id=self.request_id
                            )
                continue
                
        logger.error(f"[{self.request_id}] CHAT SESSION ENDED WITH FAILURE\nAll enabled LLM providers failed.\nLast Error: {last_error_message}")
        yield "⚠️ Error: All providers unavailable"

    async def extract_intent(
        self,
        user_message: str,
        conversation_history: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Extract the intent of the user's message using the LLM.
        Returns a dictionary with intent, search_query, and clarification_question.
        """
        import re
        msg_clean = user_message.lower().strip()
        
        # 1. Deterministic Greeting
        if re.match(r"^(hi|hello|hey|helloo|good morning|good evening|how are you|greetings|hola|thanks|ok|fine)[\s\!\.\?]*$", msg_clean):
            return {"intent": "general_query", "search_queries": []}
            
        # 2. Deterministic Capability / Discovery
        capability_patterns = [
            "tum muje kis kis trh ki jankari de sakteho",
            "what can you tell me",
            "what information can you provide",
            "what information do you have",
            "what can you help me with",
            "what do you know",
            "tell me what you know",
            "aap kya kya bata sakte ho",
            "tum kya kar sakte ho",
            "what do you do",
            "what do you work",
            "konsi konsi information",
            "what can i ask you",
            "what topics can i ask about",
            "kya kya information",
            "kya kya infromation",
            "kya kya bata",
            "kya kya puch",
            "aapke paas kya information hai",
            "kya kya jankari",
            "kya kya jaankari",
            "su su information",
            "shu shu information",
            "tamari pase su information che",
            "hu shu puchi saku",
            "shu shu jankari che",
            "tame shu janavo cho",
            "aap kis cheez ke baare mein bata sakte ho",
            "what do you know about this company",
            "તમારી પાસે કઈ માહિતી છે"
        ]
        if any(p in msg_clean for p in capability_patterns):
            return {"intent": "discovery_query", "search_queries": [user_message]}
            
        # 3. Deterministic Company Info Queries
        company_patterns = [
            # generic terms
            "ye company kya karti hai",
            "ye company kis basis",
            "what does the company do",
            "what does this company do",
            "what is the company name",
            "company ka naam kya hai",
            "company ka name kya",
            "who are you",
            "where are you located",
            "where is this company",
            "where are you based",
            "what are the business hours",
            "what are your timings",
            "when do you open",
            "how to contact",
            "how can i contact",
            "company contact",
            "company address",
            "company location",
            "aapki company",
            "is company ke baare me",
            "about the company",
            # Gujarati and Roman Gujarati terms
            "aa company shu kare che",
            "aa company su kare che",
            "aa company su kaam kare che",
            "aa compny sena upper kam kare che",
            "aa company sena upper kam kare che",
            "aa company kaya field ma kaam kare che",
            "aa company kaya area ma kaam kare che",
            "aa company no business shu che",
            "aa kai jagyae aveli che",
            "aa company kai jagyae aveli che",
            "company kai jagyae aveli che",
            "aa clinic kai jagyae aveli che",
            "aa kyare aveli che",
            "aa kya aveli che",
            "company kya aveli che",
            "aa clinic kya aveli che",
            "location kya che",
            "location kai che",
            "aa company nu location shu che",
            "which location",
            "aur location",
            "aur timings",
            "aur timing",
            "timings",
            "timing kya hai",
            "timings kya hai",
            "આ કંપની શું કરે છે",
            "આ કંપની કયા ક્ષેત્રમાં કામ કરે છે",
            "આ કંપની કઈ જગ્યાએ આવેલી છે",
            "કંપની ક્યાં આવેલી છે",
            "આ ક્લિનિક ક્યાં આવેલી છે",
            "લોકેશન ક્યાં છે",
            "aa company",
            "aa compny",
            # Hindi script
            "यह कंपनी क्या करती है",
            "कंपनी का नाम क्या है"
        ]
        
        cname = self.company_name.lower().strip() if getattr(self, "company_name", None) else ""
        if cname:
            # We match common misspellings or variants dynamically
            company_patterns.extend([
                f"what is {cname}",
                f"{cname} kya hai",
                f"{cname} kya he",
                f"{cname} shu che",
                f"{cname} shu chhe",
                f"{cname} kay aahe",
                f"{cname} kay ahe",
                f"what does {cname} do",
                f"what can {cname} do",
                f"what features does {cname} have",
                f"{cname} me kya features hain",
                f"tell me about {cname}",
                f"what do work is {cname}",
                f"how to use {cname}",
                f"how can i use {cname}"
            ])
            # Fast check - Only apply for short queries where regex normalization is safe.
        # Long queries (especially in Romanized Indian languages) must go to the LLM for proper English translation and keyword extraction.
        is_short_query = len(msg_clean.split()) <= 6
        
        if is_short_query and any(msg_clean.startswith(p) or p in msg_clean for p in company_patterns):
            from ai.language_detector import normalize_query_for_retrieval
            retrieval_query = normalize_query_for_retrieval(user_message)
            logger.info(f"[{self.request_id}] INTENT FAST-PATH\nIntent: company_info_query\nLLM Call: NOT REQUIRED\nLatency: 0.001s")
            return {"intent": "company_info_query", "search_queries": [retrieval_query]}
                
        # 4. Deterministic Document Queries
        # Expanded to cover Romanized Indian language equivalents of common doc-query terms
        words_only = re.sub(r"[^\w\s]", "", msg_clean).split()
        has_pronoun = any(word in words_only for word in ["it", "this", "that", "they", "he", "she", "those", "these", "iska", "isme", "iske", "isse", "yeh", "woh", "aa", "ena", "eni", "te", "aur", "and", "why", "how", "more"])
        if is_short_query and not conversation_history and not has_pronoun:
            # English doc-query patterns
            doc_patterns_en = [
                "features", "technologies", "database", "prompt history",
                "image gallery", "admin panel", "authentication", "objectives",
                "scope", "flow", "feature", "policy", "policies", "module", "modules"
            ]
            # Romanized Indian language equivalents (Gujarati, Hindi, Marathi)
            doc_patterns_roman = [
                # technology queries
                "technology", "technologies", "tech",
                "kai technology", "kai technologies", "vapray", "vapre", "use thai", "use che",
                "use hui", "use hain", "use karta", "use karti", "istemal",
                # features
                "features", "feature", "mukhya features", "main features",
                # database
                "database", "db", "data",
                # authentication
                "authentication", "login", "sign in",
                # scope/objectives
                "scope", "objective", "lakshya", "uddeshya",
                # admin panel
                "admin", "panel",
                # general policy
                "niti"
            ]
            all_doc_patterns = doc_patterns_en + doc_patterns_roman
            # Require at least one substantive topic word if matching generic phrases like 'kya hai' or 'shu che'
            topic_words = [w for w in words_only if w not in ["kya", "hai", "ye", "yeh", "woh", "shu", "che", "aa", "kay", "aahe", "dhanyvad", "dhanyavad", "shukriya", "thanks", "aur"]]
            has_doc_keyword = any(p in msg_clean for p in all_doc_patterns)
            has_phrase_with_topic = any(phrase in msg_clean for phrase in ["kya hai", "shu che", "kay aahe"]) and len(topic_words) >= 1
            
            if has_doc_keyword or has_phrase_with_topic:
                from ai.language_detector import normalize_query_for_retrieval
                retrieval_query = normalize_query_for_retrieval(user_message)
                logger.info(f"[{self.request_id}] INTENT FAST-PATH\nIntent: document_query\nLLM Call: NOT REQUIRED\nLatency: 0.001s")
                return {"intent": "document_query", "search_queries": [retrieval_query]}
                
        # 5. Deterministic Company Profile Fast Path (address, phone, hours)
        profile_patterns = ["address", "phone", "email", "timings", "hours", "location", "website", "details", "company details"]
        if is_short_query and any(p in msg_clean for p in profile_patterns):
            logger.info(f"[{self.request_id}] INTENT FAST-PATH\nIntent: company_info_query (profile)\nLLM Call: NOT REQUIRED\nLatency: 0.001s")
            return {"intent": "company_info_query", "search_queries": []}
            
        # 6. Source/Filename Questions
        source_patterns = ["pdf", "file", "document", "kis pdf", "source", "kahan se", "document ka naam"]
        if any(p in msg_clean for p in source_patterns):
            logger.info(f"[{self.request_id}] INTENT FAST-PATH\nIntent: system_query (source)\nLLM Call: NOT REQUIRED\nLatency: 0.001s")
            return {"intent": "system_query", "search_queries": []}
            
        system_prompt = (
            "You are an intent extraction and query rewriting engine for an AI assistant.\n"
            "Analyze the user's message and the conversation history to determine the intent and formulate precise search queries.\n\n"
            "Rules for Query Rewriting:\n"
            "0. LANGUAGE-INDEPENDENT RETRIEVAL (CRITICAL): The knowledge base is in English. You MUST always write `search_queries` in plain English, regardless of what language the user wrote in. Translate the user's intent to English search terms automatically. Example: 'RitHan ma kai technology use thai che?' → search_queries: ['RitHan technologies used']. Example: 'RitHan kya hai?' → search_queries: ['what is RitHan']. This translation is for RETRIEVAL ONLY — the final answer will be delivered in the user's language by a separate system.\n"
            "1. CONVERSATIONAL FOLLOW-UP: If the user asks a short follow-up (e.g. 'what about this?', 'and timings?', 'aur pricing?', 'why?', 'tell me more'), you MUST use the immediate conversation history to determine the active topic and entity. Rewrite it into a full, context-resolved search query (e.g. 'NovaCare Dental Clinic business hours', 'NovaCare pricing'). Do NOT return 'ambiguous' if the previous turn makes the context reasonably clear.\n"
            "1.5 CONFIRMATIONS: If the user says 'yes', 'ha', 'haan', 'correct', OR if the user ignores the AI's confirmation and just asks a related question (e.g., AI asked 'Did you mean ZeniaHR?', and User says 'how do I sign into'), you MUST resolve the intent to query about X. Example: User says 'how do I sign into', AI previously said 'Did you mean ZeniaHR?' -> search_queries: ['ZeniaHR sign in']. Set intent to 'company_info_query' or 'document_query'.\n"
            "2. DO NOT INVENT ENTITIES: If it is a new chat (no history) or no entity was established, DO NOT invent a company name (e.g. do NOT guess RitHan). If a short query like 'Which database does it use?' lacks an antecedent, return 'ambiguous' intent so the user can clarify.\n"
            "3. MULTI-PART QUESTIONS: If asking multiple separate things, split them into multiple separate queries in `search_queries`.\n"
            "4. EXACT LOOKUPS: Preserve exact names, IDs, dates, and codes.\n"
            "5. NO-CONTEXT FOLLOW-UP: If ambiguous, return 'ambiguous' intent with a clarification question in the user's language (e.g., 'Aap kis system ya project ke baare mein pooch rahe hain?'). Only ask clarification if there are multiple equally plausible referents or no active subject.\n"
            "6. COMPANY INFO: If the user asks about the company's identity, basic features, what the company is, OR asks about business hours, timings, schedule, open/close status, holidays, or specific days of the week (e.g., 'Monday ka time', 'weekend open hai?', 'kitni din close'), set intent to `company_info_query`.\n"
            "6.1 CAPABILITIES & AVAILABLE KNOWLEDGE: If the user asks what information you have, what topics you know, what you can do, or what services/products the company provides (e.g., 'aapke paas kis kis ki jankari hai', 'kis bare mein bata sakte ho', 'what do you know', 'what can you do', 'what information do you have'), set intent to `company_info_query` with search_queries: ['company overview products services capabilities']. NEVER return 'ambiguous' for these queries!\n"
            "7. GREETINGS & CHITCHAT: If the user says 'hello', 'hi', or engages in basic conversational greetings, set intent to `general_query`.\n"
            "8. DEFAULT: If the user asks about ANY company policy, modules, features, or generic company information (e.g., 'leave policy', 'company details'), set the intent to `document_query` or `company_info_query`, NEVER `ambiguous`.\n"
            "9. DEFAULT OTHERWISE: use `document_query`.\n\n"
            "Output JSON format exactly like this, and nothing else:\n"
            "{\n"
            '  "intent": "document_query" | "metadata_query" | "general_query" | "company_info_query" | "ambiguous",\n'
            '  "search_queries": ["English search query"],\n'
            '  "clarification_question": "Short clarification (if ambiguous)",\n'
            '  "is_multi_hop": false,\n'
            '  "reasoning_type": "none"\n'
            "}"
        )
        
        messages = [{"role": "system", "content": system_prompt}]
        recent = conversation_history[-6:]
        for msg in recent:
            c = (msg.get("content") or "").strip()
            if c and c != "...":
                messages.append({"role": msg.get("role", "user"), "content": c})
        messages.append({"role": "user", "content": user_message})
        
        session = await self._get_session()
        if len(msg_clean.split()) <= 2 and not conversation_history:
            default_resp = {"intent": "ambiguous", "clarification_question": "Kripya thoda aur detail me batayein."}
        else:
            default_resp = {"intent": "failed", "error": "All enabled LLM providers failed"}
        
        intent_start_time = time.perf_counter()
        # Cap intent phase to 5.0 seconds OR the remaining global budget, whichever is smaller
        global_deadline = getattr(self, "current_budget_deadline", None)
        max_intent_deadline = intent_start_time + 12.0
        deadline = min(global_deadline, max_intent_deadline) if global_deadline else max_intent_deadline
        
        # Sort providers dynamically for intent
        # NVIDIA is excluded from intent classification: it is a structured JSON task
        # requiring sub-second latency. NVIDIA's 30s timeout budget is reserved for
        # long-form generation only. Gemini and Groq handle intent reliably and fast.
        all_intent_providers = get_prioritized_providers(self.providers, getattr(self, "company_id", None), getattr(self, "agent_id", None), stage="intent")
        intent_providers = [p for p in all_intent_providers if "nvidia" not in p.provider.lower()]
        # If ALL providers are NVIDIA (edge case), fall back to full list
        if not intent_providers:
            intent_providers = all_intent_providers
            
        queue_names = " -> ".join([p.provider.lower() for p in intent_providers])
        logger.info(f"[{self.request_id}] INTENT START\nQuestion: {user_message}\nProvider Queue: {queue_names}")
        
        for i, provider in enumerate(intent_providers):
            # Fast fail if we exceeded budget
            remaining_budget = deadline - time.perf_counter()
            if remaining_budget <= 0.2:
                logger.error(f"[{self.request_id}] GLOBAL INTENT TIMEOUT EXCEEDED (remaining: {remaining_budget:.2f}s). Aborting failover.")
                break

            p_name = provider.provider.lower()
            
            if not is_provider_healthy(p_name, allow_degraded=(i == len(intent_providers) - 1)):
                if i == len(intent_providers) - 1 and i == 0:
                    pass
                else:
                    fallback_str = intent_providers[i+1].provider.lower() if i+1 < len(intent_providers) else "NONE"
                    logger.warning(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: SKIPPED (COOLDOWN)\nLatency: 0.00s\nFallback: {fallback_str}")
                    continue
                
            model = provider.model
            api_key = str(provider.api_key).strip() if provider.api_key else ""
            
            if p_name == "gemini":
                api_url = "https://generativelanguage.googleapis.com/v1beta/openai"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            elif p_name == "groq":
                api_url = "https://api.groq.com/openai/v1"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}", "User-Agent": "ZenaipexAI/1.0"}
            elif "nvidia" in p_name:
                api_url = "https://integrate.api.nvidia.com/v1"
                headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
            else:
                api_url = "https://api.sarvam.ai/v1"
                headers = {"Content-Type": "application/json", "api-subscription-key": api_key}
                
            endpoint = f"{api_url}/chat/completions"
            
            if p_name == "groq" and model in ["mixtral-8x7b-32768"]:
                model = "llama-3.3-70b-versatile"
                
            payload = {
                "model": model,
                "messages": messages,
                "max_tokens": 600,
                "temperature": 0.1,
            }
            if p_name in ["groq", "gemini"]:
                payload["response_format"] = {"type": "json_object"}

            try:
                provider_max = 30 if "nvidia" in p_name.lower() else 10
                
                remaining_providers = len(intent_providers) - i - 1
                reserve = remaining_providers * 1.5
                actual_timeout = max(3.0, min(provider_max, remaining_budget - reserve if remaining_providers > 0 else remaining_budget))
                
                logger.info(f"[BUDGET_TRACE]\nstage=intent\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nreserve={reserve:.2f}\nactual_timeout={actual_timeout:.2f}\nresult=ATTEMPTING")
                
                req_timeout = aiohttp.ClientTimeout(total=actual_timeout, connect=3, sock_read=actual_timeout)
                start_p = time.perf_counter()
                async with session.post(endpoint, json=payload, headers=headers, timeout=req_timeout) as resp:
                    elapsed = time.perf_counter() - start_p
                    if resp.status != 200:
                        status_str = f"429_QUOTA" if resp.status == 429 else f"HTTP_{resp.status}"
                        fallback_str = intent_providers[i+1].provider.lower() if i+1 < len(intent_providers) else "NONE"
                        logger.warning(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: {status_str}\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                        logger.info(f"[BUDGET_TRACE]\nstage=intent\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nreserve={reserve:.2f}\nactual_timeout={actual_timeout:.2f}\nresult={status_str}")
                        if resp.status == 429:
                            retry_after = int(resp.headers.get("Retry-After", 45))
                            record_provider_429(p_name, retry_after)
                        elif resp.status in (400, 401, 403, 404):
                            pass # Do not poison global provider health for tenant-specific auth errors
                        else:
                            record_provider_failure(p_name, f"HTTP_{resp.status}")
                        continue
                    result = await resp.json()
                    
                    if "choices" not in result or not result["choices"]:
                        fallback_str = intent_providers[i+1].provider.lower() if i+1 < len(intent_providers) else "NONE"
                        logger.warning(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: EMPTY_RESPONSE\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                        record_provider_failure(p_name)
                        continue
                        
                    msg = result["choices"][0].get("message", {})
                    content = msg.get("content")
                    
                    if content:
                        content_str = str(content)
                        if "<think>" in content_str:
                            import re
                            content_str = re.sub(r"<think>.*?</think>", "", content_str, flags=re.DOTALL).strip()
                            if "<think>" in content_str:
                                after_think = content_str.split("<think>", 1)[-1]
                                brace_idx = after_think.find("{")
                                if brace_idx != -1:
                                    content_str = after_think[brace_idx:]
                                else:
                                    content_str = content_str.split("<think>")[0].strip()
                        content = content_str
                    
                    if not content or not str(content).strip():
                        fallback_str = intent_providers[i+1].provider.lower() if i+1 < len(intent_providers) else "NONE"
                        logger.warning(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: EMPTY_RESPONSE\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                        record_provider_failure(p_name)
                        continue

                    import json
                    import ast
                    import re
                    content_str = str(content)
                    
                    # 1. Try markdown blocks
                    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content_str, flags=re.DOTALL | re.IGNORECASE)
                    if match:
                        content_str = match.group(1)
                    else:
                        # 2. Try parsing raw
                        start = content_str.find('{')
                        if start != -1:
                            end = content_str.rfind('}')
                            if end != -1:
                                temp_str = content_str[start:end+1]
                                parsed_ok = False
                                try:
                                    json.loads(temp_str)
                                    content_str = temp_str
                                    parsed_ok = True
                                except Exception:
                                    pass
                                
                                if not parsed_ok:
                                    # 3. Try finding the first valid closing brace
                                    for idx_brace in range(start + 1, len(content_str)):
                                        if content_str[idx_brace] == '}':
                                            try:
                                                json.loads(content_str[start:idx_brace+1])
                                                content_str = content_str[start:idx_brace+1]
                                                break
                                            except Exception:
                                                continue
                    
                    try:
                        parsed = json.loads(content_str)
                        if isinstance(parsed, dict) and "intent" in parsed:
                            total_intent_time = time.perf_counter() - intent_start_time
                            queries_str = "\n".join(f"- {q}" for q in parsed.get("search_queries", []))
                            logger.info(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: SUCCESS\nLatency: {elapsed:.2f}s\n\n[{self.request_id}] INTENT SUCCESS\nProvider: {p_name}\nIntent: {parsed.get('intent')}\nSearch Queries:\n{queries_str}\n\nTotal Intent Latency: {total_intent_time:.2f}s")
                            record_provider_success(p_name, getattr(self, "company_id", None), getattr(self, "agent_id", None), stage="intent", latency=elapsed)
                            return parsed
                    except Exception:
                        try:
                            parsed = ast.literal_eval(content_str)
                            if isinstance(parsed, dict) and "intent" in parsed:
                                total_intent_time = time.perf_counter() - intent_start_time
                                queries_str = "\n".join(f"- {q}" for q in parsed.get("search_queries", []))
                                logger.info(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: SUCCESS\nLatency: {elapsed:.2f}s\n\n[{self.request_id}] INTENT SUCCESS\nProvider: {p_name}\nIntent: {parsed.get('intent')}\nSearch Queries:\n{queries_str}\n\nTotal Intent Latency: {total_intent_time:.2f}s")
                                record_provider_success(p_name, getattr(self, "company_id", None), getattr(self, "agent_id", None), stage="intent")
                                return parsed
                        except Exception:
                            # 7. Robust Regex JSON Extraction
                            import re
                            json_match = re.search(r'\{.*?\}', content_str.replace('\n', ' '), re.DOTALL)
                            if json_match:
                                try:
                                    parsed = json.loads(json_match.group(0))
                                    if isinstance(parsed, dict) and "intent" in parsed:
                                        total_intent_time = time.perf_counter() - intent_start_time
                                        queries_str = "\n".join(f"- {q}" for q in parsed.get("search_queries", []))
                                        logger.info(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: SUCCESS (REGEX RECOVERED)\nLatency: {elapsed:.2f}s\n\n[{self.request_id}] INTENT SUCCESS\nProvider: {p_name}\nIntent: {parsed.get('intent')}\nSearch Queries:\n{queries_str}\n\nTotal Intent Latency: {total_intent_time:.2f}s")
                                        record_provider_success(p_name, getattr(self, "company_id", None), getattr(self, "agent_id", None), stage="intent", latency=elapsed)
                                        return parsed
                                except Exception:
                                    pass
                    fallback_str = intent_providers[i+1].provider.lower() if i+1 < len(intent_providers) else "NONE"
                    logger.warning(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: INVALID_STRUCTURED_OUTPUT\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                    record_provider_failure(p_name, "INVALID_STRUCTURED_OUTPUT")
                    continue
            except asyncio.TimeoutError:
                elapsed = time.perf_counter() - start_p
                fallback_str = intent_providers[i+1].provider.lower() if i+1 < len(intent_providers) else "NONE"
                logger.warning(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: TIMEOUT\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                logger.info(f"[BUDGET_TRACE]\nstage=intent\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nreserve={reserve:.2f}\nactual_timeout={actual_timeout:.2f}\nresult=TIMEOUT")
                record_provider_failure(p_name, "TIMEOUT")
                continue
            except Exception as exc:
                elapsed = time.perf_counter() - start_p
                fallback_str = intent_providers[i+1].provider.lower() if i+1 < len(intent_providers) else "NONE"
                logger.warning(f"[{self.request_id}] INTENT PROVIDER {p_name}\nStatus: ERROR\nLatency: {elapsed:.2f}s\nFallback: {fallback_str}")
                logger.info(f"[BUDGET_TRACE]\nstage=intent\nprovider={p_name}\nglobal_remaining={remaining_budget:.2f}\nstage_remaining={remaining_budget:.2f}\nremaining_providers={remaining_providers}\nreserve={reserve:.2f}\nactual_timeout={actual_timeout:.2f}\nresult=ERROR")
                record_provider_failure(p_name, f"ERROR_{type(exc).__name__}")
                continue
                
        total_intent_time = time.perf_counter() - intent_start_time
        logger.error(f"[{self.request_id}] INTENT FAILED\nAll enabled LLM providers failed for extract_intent.\nTotal Intent Latency: {total_intent_time:.2f}s")
        return default_resp

    async def close(self):
        """Close the aiohttp session."""
        import asyncio
        if self._session and not self._session.closed:
            sess_id = id(self._session)
            logger.info(f"[{self.request_id}] [LLM_SESSION_CLOSE]\nsession_id={sess_id}")
            await self._session.close()
            logger.info(f"[{self.request_id}] [LLM_SESSION_CLOSED]\nsession_id={sess_id}")
