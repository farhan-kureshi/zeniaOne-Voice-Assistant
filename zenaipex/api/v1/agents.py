"""
Zenaipex AI — Agents API router.

GET    /api/v1/companies/{id}/agents          List agents
POST   /api/v1/companies/{id}/agents          Create agent
GET    /api/v1/companies/{id}/agents/{aid}    Get agent
PATCH  /api/v1/companies/{id}/agents/{aid}   Update agent
DELETE /api/v1/companies/{id}/agents/{aid}   Soft-delete agent
POST   /api/v1/companies/{id}/agents/{aid}/activate  Activate draft agent
"""
from fastapi import APIRouter, Body, Depends, Path, Query, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from typing import Optional
from bson import ObjectId

from core.dependencies import get_auth_context, get_unverified_auth_context, require_admin, require_onboarding_admin, AuthContext
from core.exceptions import NotFoundError
from models.agent import AgentCreate, AgentUpdate
from services import agent_service
from ai.rag import TenantRAGPipeline
from ai.llm import AgentLLMClient
from pydantic import BaseModel
from typing import List, Dict
from datetime import datetime, timezone, timedelta
import time
from core.database import col_activity_logs
from services import conversation_service, usage_service
import logging

logger = logging.getLogger(__name__)

router = APIRouter(tags=["AI Agents"])


def _fmt_agent(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "company_id": doc["company_id"],
        "name": doc["name"],
        "slug": doc["slug"],
        "description": doc.get("description"),
        "system_prompt": doc["system_prompt"],
        "default_language": doc.get("default_language", "en-IN"),
        "supported_languages": doc.get("supported_languages", ["en-IN"]),
        "tts_voice": doc.get("tts_voice", "anushka"),
        "tts_model": doc.get("tts_model", "bulbul:v3"),
        "llm_model": doc.get("llm_model", "sarvam-105b"),
        "llm_max_tokens": doc.get("llm_max_tokens", 1200),
        "llm_temperature": doc.get("llm_temperature", 0.3),
        "greeting_messages": doc.get("greeting_messages", {}),
        "goodbye_messages": doc.get("goodbye_messages", {}),
        "knowledge_base_id": doc.get("knowledge_base_id"),
        "max_conversation_turns": doc.get("max_conversation_turns", 20),
        "silence_timeout_ms": doc.get("silence_timeout_ms", 800),
        "force_process_timeout_sec": doc.get("force_process_timeout_sec", 8.0),
        "enable_background_audio": doc.get("enable_background_audio", True),
        "status": doc.get("status", "draft"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


@router.get(
    "/companies/{company_id}/agents",
    summary="List agents",
)
async def list_agents(
    company_id: str = Path(...),
    status: Optional[str] = Query(default=None, description="Filter by status (active/draft/inactive)"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=100),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """List all AI agents for the company."""
    agents = await agent_service.list_agents(
        company_id=company_id, status=status, skip=skip, limit=limit
    )
    return {"agents": [_fmt_agent(a) for a in agents], "count": len(agents)}


@router.post(
    "/companies/{company_id}/agents",
    status_code=201,
    summary="Create a new AI agent",
)
async def create_agent(
    body: AgentCreate,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin),
):
    """
    Create a new AI agent.

    The `system_prompt` defines the agent's complete persona and behavior.
    Supports template variables: {company_name}, {user_language}, {current_date}.

    `greeting_messages` and `goodbye_messages` are dicts keyed by BCP-47 language code.

    Requires admin role.
    """
    agent = await agent_service.create_agent(
        company_id=company_id,
        data=body.model_dump(),
    )
    return _fmt_agent(agent)


@router.post(
    "/companies/{company_id}/agents/onboarding",
    status_code=201,
    summary="Create a new AI agent during onboarding",
)
async def create_agent_onboarding(
    body: AgentCreate,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_onboarding_admin),
):
    """
    Create a new AI agent during onboarding ONLY.
    Does not require email verification.
    """
    agent = await agent_service.create_agent(
        company_id=company_id,
        data=body.model_dump(),
    )
    return _fmt_agent(agent)


from pydantic import BaseModel
class GenerateRoleRequest(BaseModel):
    agent_name: str
    company_name: Optional[str] = None
    industry: Optional[str] = None
    country: Optional[str] = None

@router.post(
    "/companies/{company_id}/agents/generate-role",
    summary="Generate a draft role/purpose using AI",
)
async def generate_role(
    body: GenerateRoleRequest,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """
    Generate a professional draft role/purpose for a new agent.
    This does NOT spend user quota or tokens (uses platform default).
    """
    # Create a dummy agent document to use the standard LLM client
    agent_doc = {
        "company_id": company_id,
        "name": body.agent_name,
        "llm_model": "sarvam-105b", # Fast generic model
        "llm_max_tokens": 150,
        "llm_temperature": 0.7,
        "system_prompt": "You are a prompt engineering assistant."
    }
    
    prompt = f"The user is onboarding a new company into an AI voice agent platform.\n"
    if body.company_name:
        prompt += f"Company Name: {body.company_name}\n"
    if body.industry:
        prompt += f"Industry: {body.industry}\n"
        
    prompt += f"\nWrite a professional system role/purpose for their new AI voice agent named '{body.agent_name}'. "
    prompt += f"It should be approx 2-3 sentences long. "
    prompt += f"Write ONLY the draft role, starting with 'You are...'. Do not include any introductory text or quotes."
    
    from ai.llm import AgentLLMClient
    
    try:
        async with await AgentLLMClient.create(agent_doc, request_id="REQ-GENROLE") as llm:
            response, _, _ = await llm.generate([{"role": "user", "content": prompt}], stage="generation")
            
            # Clean up response if it wrapped in quotes
            clean_role = response.strip()
            if clean_role.startswith('"') and clean_role.endswith('"'):
                clean_role = clean_role[1:-1]
            if clean_role.startswith("'") and clean_role.endswith("'"):
                clean_role = clean_role[1:-1]
                
            return {"draft_role": clean_role}
    except Exception as e:
        logger.error(f"Failed to generate role: {e}")
        return {"draft_role": f"You are the customer support assistant for {body.company_name or 'the company'}. Help customers with product information, orders, and general support. Respond clearly, professionally, and accurately using the available knowledge."}


@router.get(
    "/companies/{company_id}/agents/{agent_id}",
    summary="Get agent details",
)
async def get_agent(
    company_id: str = Path(...),
    agent_id: str = Path(...),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """Get full agent configuration."""
    agent = await agent_service.get_agent(company_id, agent_id)
    if not agent:
        raise NotFoundError("Agent")
    return _fmt_agent(agent)


@router.patch(
    "/companies/{company_id}/agents/{agent_id}",
    summary="Update agent",
)
async def update_agent(
    body: AgentUpdate,
    company_id: str = Path(...),
    agent_id: str = Path(...),
    ctx: AuthContext = Depends(require_onboarding_admin),
):
    """Update agent configuration. Only provided fields are updated. Requires admin."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    agent = await agent_service.update_agent(company_id, agent_id, updates)
    if not agent:
        raise NotFoundError("Agent")
    return _fmt_agent(agent)


@router.post(
    "/companies/{company_id}/agents/{agent_id}/activate",
    summary="Activate a draft agent",
)
async def activate_agent(
    company_id: str = Path(...),
    agent_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin),
):
    """Set agent status to 'active' so it can handle live calls."""
    agent = await agent_service.update_agent(
        company_id, agent_id, {"status": "active"}
    )
    if not agent:
        raise NotFoundError("Agent")
    return {"success": True, "status": "active", "agent_id": agent_id}


@router.post(
    "/companies/{company_id}/agents/{agent_id}/deactivate",
    summary="Deactivate an agent",
)
async def deactivate_agent(
    company_id: str = Path(...),
    agent_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin),
):
    """Set agent status to 'inactive'."""
    agent = await agent_service.update_agent(
        company_id, agent_id, {"status": "inactive"}
    )
    if not agent:
        raise NotFoundError("Agent")
    return {"success": True, "status": "inactive", "agent_id": agent_id}


@router.delete(
    "/companies/{company_id}/agents/{agent_id}",
    summary="Delete agent (soft-delete)",
)
async def delete_agent(
    company_id: str = Path(...),
    agent_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin),
):
    """
    Soft-delete an agent. Sets status to 'deleted'.
    Also deactivates all channels using this agent.
    Requires admin.
    """
    success = await agent_service.delete_agent(company_id, agent_id)
    if not success:
        raise NotFoundError("Agent")
    return {"success": True, "deleted": agent_id}


class AgentTestChatRequest(BaseModel):
    message: str
    history: List[Dict[str, str]] = []
    conversation_id: Optional[str] = None
    document_ids: Optional[List[str]] = None


@router.post(
    "/companies/{company_id}/agents/{agent_id}/test-chat",
    summary="Test agent using text chat",
)
async def agent_test_chat(
    body: AgentTestChatRequest,
    company_id: str = Path(...),
    agent_id: str = Path(...),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """
    Test the agent configuration and its associated knowledge base using a text interface.
    This does not use TTS/STT and is meant for the AI Playground.
    """
    agent = await agent_service.get_agent(company_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
        
    import uuid
    
    req_id = f"REQ-{uuid.uuid4().hex[:8].upper()}"
    total_start_time = time.perf_counter()
    
    agent_name = agent.get('name', 'Unknown')
    logger.info(f"[{req_id}] AI REQUEST START\nAgent: {agent_name} ({agent_id})\nCompany ID: {company_id}\nQuery: {body.message}")
        
    # --- DETERMINISTIC GREETING GUARD ---
    from ai.language_detector import detect_language as _detect_lang, get_fallback_message as _get_fallback, get_error_fallback_message as _get_error_fallback
    
    # Detect language once upfront — used for both greeting localization and fallback strings
    _lang_result = _detect_lang(body.message, body.history)
    _detected_lang = _lang_result.lang
    _detected_script = _lang_result.script
    
    # Fetch company name & profile info
    from core.database import col_companies
    from bson import ObjectId
    company = await col_companies().find_one({"_id": ObjectId(company_id)})
    
    from ai.fast_path import check_deterministic_fast_path
    fast_response = check_deterministic_fast_path(
        message=body.message,
        company=company,
        agent=agent,
        detected_lang=_detected_lang,
        detected_script=_detected_script
    )
    
    if fast_response:
        logger.info(f"[{req_id}] SMART_ROUTER Level 1 (Deterministic Fast Path) matched. LLM_CALLED=false PINECONE_CALLED=false duration_ms={(time.perf_counter() - total_start_time)*1000:.2f}")

    # Initialize all telemetry/result variables safely before branching
    search_queries = []
    retrieved_count = 0
    retained_count = 0
    scores = []
    retrieval_latency = 0.0
    generation_latency = 0.0
    val_result = {"grounded": True, "details": "Initialized"}
    context_docs = []
    diagnostics = {}
    is_generation_fallback = False
        
    if fast_response:
        # Bypass all LLM, RAG, and Billing. Skip to conversation persistence.
        response = fast_response
        val_result["details"] = "Deterministic profile/greeting"
        # Do not increment usage for fast greetings
    else:
        # Check AI Credit Limit
        if not await usage_service.check_ai_credit_limit(company_id):
            return {"answer": "AI credit limit reached. Upgrade your plan to continue.", "sources": []}
            
        # Context collections configured
        from core.config import settings as _settings
        if not _settings.sarvam_api_key:
            return {"answer": "⚠️ AI service is not configured. Please set SARVAM_API_KEY.", "sources": []}
            
        # Step 6: Contextual Follow-up Fast Route
        from ai.context_resolver import resolve_followup
        resolver_result = resolve_followup(
            message=body.message,
            conversation_id=body.conversation_id,
            history=body.history,
            company=company,
            agent=agent,
            detected_lang=_detected_lang,
            detected_script=_detected_script,
        )
        
        intent = "document_query"
        
        if resolver_result and "response" in resolver_result:
            # Resolved to an expanded fast-path response
            response = resolver_result["response"]
            val_result["details"] = f"Contextual follow-up fast path ({resolver_result.get('resolved_subject')})"
            # We skip LLM block entirely, so we simulate skipping it:
            fast_response = response
        else:
            try:
                llm = await AgentLLMClient.create(agent, request_id=req_id)
                llm.set_budget(10.0)
            except RuntimeError as e:
                return {"answer": str(e), "sources": []}
                
            try:  # Lifecycle fix
                # 1. Intent Extraction
                if resolver_result and "rewritten_query" in resolver_result:
                    # Skip intent extraction for resolved RAG subjects
                    intent = resolver_result["intent"]
                    intent_data = {"intent": intent, "search_queries": [resolver_result["rewritten_query"]]}
                    search_queries = intent_data["search_queries"]
                    logger.info(f"[{req_id}] SMART_ROUTER Level 2 (Context Resolver) bypassed LLM intent. Resolved to: {intent}")
                else:
                    intent_data = await llm.extract_intent(body.message, body.history)
                    intent = intent_data.get("intent", "document_query")
                    # Phase 6: Handle multiple search queries for multi-part/multi-document intent
                    search_queries = intent_data.get("search_queries", [])
                    logger.info(f"[{req_id}] SMART_ROUTER Level 2 (Intent Engine) resolved to: {intent}")
                if not search_queries:
                    search_queries = [intent_data.get("search_query", body.message)]
                
                # If extract_intent failed totally, fallback safely without failing
                if intent == "failed" and "All enabled LLM providers failed" in str(intent_data):
                    logger.warning(f"[{req_id}] INTENT EXHAUSTED: Returning localized safe error message.")
                    response = _get_error_fallback(_detected_lang, _detected_script)
                    is_generation_fallback = True
                    intent = "failed"
                    token_usage = {}
                    context_docs = []
                
                # 2. Routing based on Intent
                if intent == "ambiguous":
                    clarification = intent_data.get("clarification_question", "Kripya clarify karein.")
                    response = clarification
                    token_usage = {}
                    logger.info(f"[{req_id}] AI REQUEST SUCCESS\nTotal Latency: {(time.perf_counter() - total_start_time):.2f}s\nResolution: ambiguous")
                
                elif intent == "metadata_query":
                    # Phase 12 Security: Do not leak document inventory to customers
                    response = (
                        "Main internal company files ya storage details share nahi karta. "
                        "Lekin aap company policies, services, ya products ke baare mein sawal pooch sakte hain. "
                        "Main aapki kya madad karu?"
                    )
                    token_usage = {}
                    logger.info(f"[{req_id}] AI REQUEST SUCCESS\nTotal Latency: {(time.perf_counter() - total_start_time):.2f}s\nResolution: metadata_refusal")
                
                elif intent == "system_query":
                    # Deterministic source info (Fast Path)
                    response = _get_fallback(_detected_lang, _detected_script)
                    token_usage = {}
                    logger.info(f"[{req_id}] AI REQUEST SUCCESS\nTotal Latency: {(time.perf_counter() - total_start_time):.2f}s\nResolution: system_query_fallback")
                
                elif intent == "general_query":
                    # Deterministic greeting fallback (preserves intended behavior for casual questions that bypassed the fast-path regex)
                    c_name = company.get("name", "our company") if company else "our company"
                    if c_name.upper() == "INTERNAL / PLATFORM" or c_name == "ZeniaAI Internal Workspace":
                        c_name = "ZeniaOne"
                
                    # Override name if this is the internal admin workspace but a custom customer agent
                    if c_name == "ZeniaOne" and agent.get("agent_type") != "platform_admin":
                        c_name = agent.get("name", "our company").replace(" Agent", "").replace("ZeniaAI", "ZeniaOne").replace("Zenia AI", "ZeniaOne").strip() or "our company"
                    
                    if _detected_script == "devanagari":
                        response = f"मैं ठीक हूँ, धन्यवाद! आप {c_name} के बारे में क्या जानना चाहेंगे?"
                    elif _detected_script == "gujarati_script":
                        response = f"હું મજામાં છું, આભાર! તમે {c_name} વિશે શું જાણવા માંગો છો?"
                    elif _detected_lang in ["hindi", "hinglish"]:
                        response = f"Main theek hoon, shukriya! Aap {c_name} ke baare mein kya jaanna chahenge?"
                    elif _detected_lang == "gujarati":
                        response = f"Hu majama chu, aabhar! Tame {c_name} vishe shu janva mango cho?"
                    else:
                        response = f"I'm doing well, thank you! What would you like to know about {c_name}?"
                    
                    token_usage = {}
                    logger.info(f"[{req_id}] AI REQUEST SUCCESS\nTotal Latency: {(time.perf_counter() - total_start_time):.2f}s\nResolution: general_query_greeting")
                
                elif intent in ["document_query", "company_info_query", "discovery_query"]:
                    from ai.evaluation import RAGEvaluator
                    rag = TenantRAGPipeline(namespace=company_id, agent_doc=agent)
                
                    if rag.rag_enabled() or body.document_ids:
                        try:
                            all_raw_docs = []
                            seen_texts = set()
                        
                            if intent == "discovery_query":
                                all_raw_docs = []
                                all_candidates_pool = []
                                retrieval_latency = 0.0
                                logger.info(f"[{req_id}] FAST-PATH: discovery_query bypassing Pinecone.")
                            else:
                                # Phase 11: Multi-Hop & Dependent Reasoning Engine
                                from ai.multi_hop import MultiHopEngine
                            
                                all_raw_docs, all_candidates_pool, retrieval_latency = await MultiHopEngine.resolve_dependent_queries(
                                    agent_llm=llm,
                                    rag_pipeline=rag,
                                    intent_data=intent_data,
                                    document_ids=body.document_ids,
                                    request_id=req_id
                                )
                            
                                # Re-sort combined results by rerank score
                                all_raw_docs.sort(key=lambda x: x.get("rerank_score", x.get("score", 0)), reverse=True)
                        
                            # Confidence/Relevance Gate: Ensure we don't send garbage context
                            if intent == "discovery_query":
                                context_docs = []
                            elif intent == "company_info_query" or (all_raw_docs and max(d.get("rerank_score", d.get("score", 0)) for d in all_raw_docs) > 0.2):
                                context_docs = all_raw_docs[:12] # Cap max combined context chunks
                            
                                # Phase 10: Structural Assembly & Neighbor Expansion
                                from ai.assembly import ContextAssembler
                                ca_start = time.perf_counter()
                                context_docs = ContextAssembler.assemble(context_docs, all_candidates_pool, rag._get_vs(), request_id=req_id)
                                ca_time = time.perf_counter() - ca_start
                                logger.info(f"[{req_id}] CONTEXT ASSEMBLY\nChunks Before: {len(all_raw_docs[:12])}\nChunks After: {len(context_docs)}\nLatency: {ca_time:.2f}s")
                            else:
                                logger.info(f"RAG relevance gate blocked context for queries: {search_queries}")
                                context_docs = None
                            
                            # Save stats for evaluation
                            retrieved_count = len(all_candidates_pool) if all_candidates_pool else len(all_raw_docs)
                            retained_count = len(context_docs) if context_docs else 0
                            scores = [d.get("rerank_score", d.get("score", 0)) for d in all_raw_docs]
                            
                        except Exception as rag_err:
                            logger.warning(f"RAG retrieval skipped or failed: {rag_err}")
                            retrieval_latency = 0
                            retrieved_count = 0
                            retained_count = 0
                            scores = []
                            context_docs = None
                        
                    # CRITICAL FIX: Empty Context Safety Guard
                    # 1. Technical failure (context_docs is None) -> ALWAYS fallback
                    # 2. Empty retrieval (context_docs == []) -> Fallback if document_query or company_info_query
                
                    if intent in ["document_query", "company_info_query"] and (not context_docs or len(context_docs) == 0):
                        logger.info(f"[{req_id}] RAG returned no evidence for {intent} '{body.message}', short-circuiting to safe fallback.")
                        response = _get_fallback(_detected_lang, _detected_script)
                        token_usage = {}
                    else:
                        # discovery_query skips these empty RAG checks because its answers are derived from the dynamically injected AVAILABLE KNOWLEDGE TOPICS.
                        try:
                            gen_start = time.time()
                            response, token_usage = await llm.generate(
                                user_message=body.message,
                                conversation_history=body.history,
                                context_docs=context_docs,
                                intent=intent,
                            )
                            generation_latency = time.time() - gen_start
                            if intent == "company_info_query":
                                logger.info("[COMPANY_INFO_SOURCE] field=company_metadata source=rag")
                        except Exception as llm_err:
                            logger.error(f"LLM generate exception: {llm_err}", exc_info=True)
                            response = "⚠️ Error: All providers unavailable"
                            token_usage = {}
                        
                        if response and "Error: All providers unavailable" in response:
                            logger.warning(f"[{req_id}] GENERATION EXHAUSTED: Returning localized safe error message.")
                            response = _get_error_fallback(_detected_lang, _detected_script)
                            is_generation_fallback = True
                    
                        if not response:
                            logger.error(f"[{req_id}] AI REQUEST FAILED\nTotal Latency: {(time.perf_counter() - total_start_time):.2f}s\nReason: LLM returned None")
                            response = _get_error_fallback(_detected_lang, _detected_script)
                            is_generation_fallback = True
    
            finally:
                await llm.close()
        if str(response).startswith("⚠️ Error:") or "AI service is temporarily unavailable" in str(response):
            # LLM provider returned an error, return directly without charging usage or saving to conversation history
            logger.error(f"[{req_id}] AI REQUEST FAILED\nTotal Latency: {(time.perf_counter() - total_start_time):.2f}s\nReason: LLM Provider Error ({response})")
            return {"answer": _get_error_fallback(_detected_lang, _detected_script), "sources": []}
            
        # Phase 7: Deterministic Answer Grounding Validation & Diagnostics
        from ai.evaluation import RAGEvaluator
        val_result = RAGEvaluator.validate_grounding(response, context_docs)
        
        # Apply claim validation safety fallback
        if not val_result["grounded"] and "Mujhe is information" not in response:
            response += "\n\n*(Note: Some specific identifiers or dates in this answer could not be confidently verified against the company documents.)*"
    
        rag_intents = ["document_query", "company_info_query", "discovery_query"]
        diagnostics = RAGEvaluator.generate_diagnostics(
            queries=search_queries if intent in rag_intents else [body.message],
            retrieved_count=retrieved_count if intent in rag_intents else 0,
            retained_count=retained_count if intent in rag_intents else 0,
            scores=scores if intent in rag_intents else [],
            retrieval_latency=retrieval_latency if intent in rag_intents else 0.0,
            generation_latency=generation_latency,
            validation_result=val_result,
            request_id=req_id
        )
        
        # Increment Usage
        await usage_service.increment_usage(
            company_id=company_id,
            call_duration_seconds=0,
            llm_calls=1,
            rag_queries=1 if context_docs else 0,
            input_tokens=token_usage.get("prompt_tokens", 0),
            output_tokens=token_usage.get("completion_tokens", 0),
            total_tokens=token_usage.get("total_tokens", 0),
            direction="test-chat"
        )

    recent_conv = None
    if body.conversation_id:
        from core.database import col_conversations
        from bson import ObjectId
        if ObjectId.is_valid(body.conversation_id):
            recent_conv = await col_conversations().find_one({
                "company_id": company_id,
                "_id": ObjectId(body.conversation_id)
            })
    else:
        # User started a new chat or temporary chat (no valid id provided). Do not auto-resume old chats.
        pass

    if not recent_conv:
        recent_conv = await conversation_service.create_conversation(
            company_id=company_id,
            agent_id=agent_id,
            direction="test-chat",
            caller_phone="Super Admin",
        )
        # Log activity for a new test chat
        await col_activity_logs().insert_one({
            "actor_name": ctx.user.get("name", "Admin"),
            "actor_email": ctx.user.get("email"),
            "action": "test_chat_started",
            "target": agent.get("name", "Agent"),
            "details": f"Started a new test chat session with agent {agent_id}",
            "created_at": datetime.now(timezone.utc)
        })

    conv_id = str(recent_conv["_id"])
    await conversation_service.add_message(company_id, conv_id, "user", body.message)
    await conversation_service.add_message(company_id, conv_id, "assistant", response)
    
    # Step 6: Record subject for contextual follow-up fast route
    from ai.context_resolver import record_subject
    record_subject(conv_id, response, body.message)
    
    # Update ended_at to keep the session alive for 1 hour
    await conversation_service.end_conversation(company_id, conv_id, status="active")
    
    # Build sanitized sources: convert internal filenames to clean topic labels.
    # IMPORTANT: Raw filenames (e.g. "NovaCare_Dental_Clinic_Guide.pdf") must NEVER
    # be exposed in the customer-facing UI. We strip the extension and normalise casing.
    def _source_to_label(raw_source: str) -> str:
        """Convert an internal filename/document_id to a human-readable topic label."""
        if not raw_source:
            return ""
        # Strip path separators, use only the basename
        name = raw_source.replace("\\", "/").split("/")[-1]
        # Remove common file extensions
        for ext in (".pdf", ".docx", ".doc", ".txt", ".md", ".csv"):
            if name.lower().endswith(ext):
                name = name[:-(len(ext))]
                break
        # Replace underscores and hyphens with spaces, title-case
        label = name.replace("_", " ").replace("-", " ").strip().title()
        return label if label else ""
    
    sources = []
    if context_docs and val_result.get("grounded", False):
        seen_labels: set = set()
        for d in context_docs:
            raw = d.get("source") or d.get("metadata", {}).get("document_id") or ""
            label = _source_to_label(raw)
            if label and label not in seen_labels:
                seen_labels.add(label)
                sources.append({"label": label, "score": round(d.get("score", 0), 3)})


    total_latency = time.perf_counter() - total_start_time
    
    # TELEMETRY LOGGING (Task 10)
    import json
    telemetry = {
        "request_id": req_id,
        "company_id": company_id,
        "agent_id": agent_id,
        "total_latency_s": round(total_latency, 3),
        "intent_latency_s": round(getattr(llm, "intent_latency", 0) if 'llm' in locals() else 0, 3),
        "retrieval_latency_s": round(retrieval_latency, 3),
        "generation_latency_s": round(generation_latency, 3),
        "fast_path_used": bool(fast_response),
        "context_chunks_used": len(context_docs) if context_docs else 0,
        "grounded": val_result.get("grounded", False),
    }
    logger.info(f"[{req_id}] REQUEST_TELEMETRY: {json.dumps(telemetry)}")
    
    if is_generation_fallback:
        logger.info(f"[{req_id}] AI REQUEST FAILED\nTotal Latency: {total_latency:.2f}s\nResolution: FALLBACK")
    else:
        logger.info(f"[{req_id}] AI REQUEST SUCCESS\nTotal Latency: {total_latency:.2f}s\nResolution: answered")
    
    return {
        "answer": response,
        "sources": sources,
        "conversation_id": conv_id,
        "diagnostics": diagnostics # Expose safe diagnostics for admin testing UI
    }


@router.post(
    "/companies/{company_id}/agents/{agent_id}/conversations",
    summary="Create a new conversation",
)
async def create_agent_conversation(
    company_id: str = Path(...),
    agent_id: str = Path(...),
    ctx: AuthContext = Depends(get_auth_context),
):
    """
    Explicitly initialize an empty conversation before starting a chat session.
    """
    agent = await agent_service.get_agent(company_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    new_conv = await conversation_service.create_conversation(
        company_id=company_id,
        agent_id=agent_id,
        direction="test-chat",
        caller_phone="Voice Chat",
    )
    conv_id = str(new_conv["_id"])
    
    logger.info(f"[VOICE_CONVERSATION] event=created conversation_id={conv_id} agent_id={agent_id} source=voice")
    
    return {"conversation_id": conv_id}


def calculate_wav_stats(wav_bytes):
    try:
        import wave
        import io
        import math
        import struct
        with wave.open(io.BytesIO(wav_bytes), 'rb') as wf:
            channels = wf.getnchannels()
            sample_width = wf.getsampwidth()
            framerate = wf.getframerate()
            n_frames_header = wf.getnframes()
            frames = wf.readframes(n_frames_header)
            
            # The header might have a dummy size (e.g. 0xFFFFFFFF) due to ffmpeg pipe output
            actual_n_frames = len(frames) // (channels * sample_width)
            duration = actual_n_frames / framerate if framerate > 0 else 0
            
            if sample_width == 2:
                samples = struct.unpack(f'<{actual_n_frames * channels}h', frames)
                sum_squares = sum(s * s for s in samples)
                rms = math.sqrt(sum_squares / len(samples)) if samples else 0
                peak = max(abs(s) for s in samples) if samples else 0
                speech_samples = sum(1 for s in samples if abs(s) > 500)
                speech_activity = (speech_samples / len(samples)) * 100 if samples else 0
                
                leading_silence_frames = 0
                for s in samples:
                    if abs(s) > 500:
                        break
                    leading_silence_frames += 1
                
                trailing_silence_frames = 0
                for s in reversed(samples):
                    if abs(s) > 500:
                        break
                    trailing_silence_frames += 1

                leading_silence_ms = int((leading_silence_frames / len(samples)) * duration * 1000) if samples else 0
                trailing_silence_ms = int((trailing_silence_frames / len(samples)) * duration * 1000) if samples else 0

                return {
                    "duration_ms": int(duration * 1000),
                    "sample_rate": framerate,
                    "channels": channels,
                    "rms": rms,
                    "peak": peak,
                    "speech_ratio": speech_activity,
                    "leading_silence_ms": leading_silence_ms,
                    "trailing_silence_ms": trailing_silence_ms
                }
    except Exception as e:
        pass
    return None


@router.post(
    "/companies/{company_id}/agents/{agent_id}/speak",
    summary="TTS-only: synthesise text with the agent's voice",
)
async def agent_speak(
    company_id: str = Path(...),
    agent_id: str = Path(...),
    body: dict = Body(...),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """
    Lightweight TTS-only endpoint used for the Voice Mode welcome greeting.
    Does NOT call STT, LLM, or RAG.  Returns audio_base64 only.
    """
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")

    agent = await agent_service.get_agent(company_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    from modules.sarvam_tts import realtime_tts
    import base64

    lang    = agent.get("default_language", "en-IN")
    speaker = agent.get("tts_voice", "anushka")

    logger.info(f"[VOICE_SPEAK_TTS] text_len={len(text)} lang={lang} speaker={speaker}")
    try:
        tts_bytes = await realtime_tts(text=text, language=lang, speaker=speaker)
    except ValueError as exc:
        logger.error(f"[VOICE_SPEAK_TTS_ERROR] Invalid Configuration: {exc}")
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(f"[VOICE_SPEAK_TTS_ERROR] {exc}")
        raise HTTPException(status_code=502, detail="TTS synthesis failed")

    if not tts_bytes:
        raise HTTPException(status_code=502, detail="TTS returned empty audio")

    audio_b64 = base64.b64encode(tts_bytes).decode("utf-8")
    logger.info(f"[VOICE_SPEAK_TTS_OK] audio_bytes={len(tts_bytes)}")
    return {"audio_base64": audio_b64, "audio_bytes": len(tts_bytes)}

def normalize_known_entities(transcript: str, company_name: str) -> tuple[str, bool, str, float, str]:
    """
    Conservatively normalizes phonetic variants of known entities (e.g. ZeniaHR)
    using deterministic fuzzy matching while protecting generic HR terms.
    """
    if not transcript:
        return transcript, False, "none", 0.0, ""
        
    import re
    import difflib
    
    cname = company_name.strip() if company_name else ""
    cname_lower = cname.lower()
    
    known_entities = []
    source = "company"
    
    if cname and cname_lower not in ["internal / platform"]:
        known_entities.append(cname)
    else:
        # Minimal safe fallback ONLY for platform test agent
        known_entities.extend(["ZeniaHR", "ZeniaOne"])
        source = "platform_fallback"
        
    words = transcript.split()
    changed = False
    reason = "none"
    max_conf = 0.0
    matched_cand = ""
    matched_canon = ""
    
    # Generic HR phrases to protect
    protected_norm = [
        'hrpolicy', 'hrmanager', 'hrdepartment', 'humanresources',
        'payrollhr', 'attendancesystem', 'attendancepolicy'
    ]
    
    stop_words = {
        'is', 'are', 'was', 'were', 'and', 'or', 'but', 'to', 'for', 
        'with', 'of', 'in', 'on', 'at', 'what', 'who', 'how', 'kya', 'hai'
    }
    
    def normalize_candidate(text: str) -> str:
        return re.sub(r'[\W_]+', '', text.lower())
        
    i = 0
    while i < len(words):
        best_score = 0.0
        best_end = -1
        best_cand = ""
        best_canon = ""
        
        # Check window of 1 to 5 words
        for n in range(1, min(6, len(words) - i + 1)):
            span_words = words[i:i+n]
            span_text = " ".join(span_words)
            cand_norm = normalize_candidate(span_text)
            
            if cand_norm in protected_norm:
                continue
                
            # Restrict to plausible lengths
            if 3 <= len(cand_norm) <= 40:
                # Direct phonetic and script matches for ZeniaHR
                if "ZeniaHR" in known_entities:
                    if cand_norm in ['ज़ेनियाएचआर', 'ज़ेनियायाएचआर', 'zeniahr', 'zenehr', 'zenyahr', 'zinniahr', 'zenerhr']:
                        if 1.0 > best_score:
                            best_score = 1.0
                            best_end = i + n
                            best_cand = span_text
                            best_canon = "ZeniaHR"
                    elif cand_norm.endswith('hr') and cand_norm[0] in 'jgz':
                        score = 0.85
                        if cand_norm in ['jnehr', 'jnnhr', 'jnhr', 'jrhr', 'janyahr', 'janiahr', 'jenyahr', 'jeniahr', 'geniahr', 'genyfxhr', 'ziniahr', 'zenniahr']:
                            score = 1.0
                        if score > best_score:
                            best_score = score
                            best_end = i + n
                            best_cand = span_text
                            best_canon = "ZeniaHR"

                # Direct phonetic and script matches for ZeniaOne
                if "ZeniaOne" in known_entities:
                    if cand_norm in ['ज़ेनियावन', 'zeniaone', 'zinniaone', 'zenyaone', 'zeneone']:
                        if 1.0 > best_score:
                            best_score = 1.0
                            best_end = i + n
                            best_cand = span_text
                            best_canon = "ZeniaOne"
                    elif cand_norm.endswith('one') and cand_norm[0] in 'jgz':
                        score = 0.85
                        if cand_norm in ['ziniaone', 'zenniaone', 'jeniaone', 'geniaone']:
                            score = 1.0
                        if score > best_score:
                            best_score = score
                            best_end = i + n
                            best_cand = span_text
                            best_canon = "ZeniaOne"
                            
                else:
                    for canon in known_entities:
                        canon_n = normalize_candidate(canon)
                        if not canon_n: continue
                        
                        # Prevent consuming leading/trailing grammatical words
                        if len(span_words) > 1:
                            first_word_norm = normalize_candidate(span_words[0])
                            last_word_norm = normalize_candidate(span_words[-1])
                            canon_words_norm = [normalize_candidate(w) for w in canon.split()]
                            
                            if first_word_norm in stop_words and first_word_norm not in canon_words_norm:
                                continue
                            if last_word_norm in stop_words and last_word_norm not in canon_words_norm:
                                continue
                        
                        ratio = difflib.SequenceMatcher(None, cand_norm, canon_n).ratio()
                        
                        # Apply domain-specific bonuses only for platform fallbacks
                        if canon == "ZeniaHR" and cand_norm.endswith('hr'):
                            ratio += 0.1
                        elif canon == "ZeniaOne" and cand_norm.endswith('one'):
                            ratio += 0.1
                            
                        if ratio > best_score:
                            best_score = ratio
                            best_end = i + n
                            best_cand = span_text
                            best_canon = canon
                        
        if best_score >= 0.75:
            last_word = words[best_end - 1]
            m = re.search(r'([\'\u2019]s|[^a-zA-Z0-9])+$', last_word, re.IGNORECASE)
            suffix = m.group(0) if m else ""
                
            replacement = best_canon + suffix
            if best_cand != replacement:
                changed = True
                
            words[i:best_end] = [replacement]
            reason = "known_entity_fuzzy_match" if best_score < 1.0 else "known_entity_exact_match"
            if best_score > max_conf:
                max_conf = best_score
                matched_cand = best_cand
                matched_canon = best_canon
            i += 1 
        else:
            i += 1
            
    new_transcript = " ".join(words)
    return new_transcript, changed, reason, max_conf, matched_cand, matched_canon, source

@router.post(
    "/companies/{company_id}/agents/{agent_id}/voice-chat",
    summary="Test agent using voice chat",
)
async def test_agent_voice_chat(
    company_id: str = Path(...),
    agent_id: str = Path(...),
    audio: UploadFile = File(...),
    history: str = Form("[]"),
    conversation_id: Optional[str] = Form(None),
    speech_start_ms: Optional[int] = Form(None),
    speech_end_ms: Optional[int] = Form(None),
    pending_transcript: Optional[str] = Form(None),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """
    Test the agent using voice input. Converts audio to text via Sarvam STT,
    processes it through the existing text chat pipeline, and generates audio
    output via Sarvam TTS.
    """
    agent = await agent_service.get_agent(company_id, agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    import json
    import base64


    from modules.sarvam_tts import realtime_stt, realtime_tts  # Both helpers live in sarvam_tts

    # 1. Read Audio and Transcribe
    audio_data = await audio.read()
    logger.info(f"[VOICE_STT_START] agent={agent_id} conv={conversation_id} audio_bytes={len(audio_data) if audio_data else 0}")
    
    # Simple check for empty audio
    if not audio_data or len(audio_data) < 100:
        logger.warning(f"[VOICE_STT_START] Audio too small ({len(audio_data) if audio_data else 0} bytes), skipping STT")
        return {
            "answer": "I couldn't hear anything. Please try speaking again.",
            "sources": [],
            "conversation_id": conversation_id,
            "transcript": "",
            "audio_base64": ""
        }

    lang = agent.get("default_language", "en-IN")
    
    # The browser sends audio/webm (or MP4), but Sarvam STT WebSocket ONLY supports strictly formatted audio/wav.
    # Convert using ffmpeg in memory.
    import subprocess
    import shutil
    import wave
    import io
    import tempfile
    import os
    
    stats = None
    logger.info(f"[VOICE_INPUT_AUDIO] bytes={len(audio_data) if audio_data else 0} content_type={audio.content_type} filename={audio.filename} speech_start={speech_start_ms} speech_end={speech_end_ms}")
    
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        logger.error("[VOICE_FFMPEG_ERROR] FFmpeg executable not found in PATH")
        raise HTTPException(status_code=422, detail="Voice input couldn't be processed. Please try again.")
        
    logger.info(f"[VOICE_FFMPEG_BINARY] path={ffmpeg_path}")

    # Calculate FFmpeg trim boundaries
    trim_args = []
    if speech_start_ms is not None and speech_end_ms is not None:
        start_sec = max(0, speech_start_ms - 300) / 1000.0
        # Add 300ms pre-roll and ~800ms trailing silence to duration
        duration_sec = ((speech_end_ms - speech_start_ms) + 1100) / 1000.0
        trim_args = ["-ss", f"{start_sec:.3f}", "-t", f"{duration_sec:.3f}"]
        logger.info(f"[VOICE_FFMPEG_TRIM] start_sec={start_sec:.3f} duration_sec={duration_sec:.3f}")

    # Optimization: Removed synchronous disk-write FFmpeg validation step

    utterance_id = int(time.time()*1000)

    try:
        logger.info("[VOICE_STT_START] Converting incoming audio to 16kHz WAV pcm_s16le...")
        process = subprocess.run(
            [ffmpeg_path, "-y", *trim_args, "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", "-f", "wav", "pipe:1"],
            input=audio_data,
            capture_output=True
        )
        if process.returncode == 0 and len(process.stdout) > 0:
            audio_data = process.stdout
            
            # Validate output WAV
            try:
                with wave.open(io.BytesIO(audio_data), 'rb') as wf:
                    channels = wf.getnchannels()
                    sample_width = wf.getsampwidth()
                    sample_rate = wf.getframerate()
                    frames_header = wf.getnframes()
                    
                    # Compute actual frames bypassing dummy header sizes
                    actual_frames = len(audio_data) // (channels * sample_width) - 11
                    if actual_frames < 0: actual_frames = 0
                    
                    duration_ms = (actual_frames / float(sample_rate)) * 1000 if sample_rate > 0 else 0
                    
                    if channels != 1 or sample_rate != 16000 or sample_width != 2 or actual_frames == 0:
                        raise ValueError(f"Invalid WAV geometry: ch={channels} rate={sample_rate} width={sample_width} actual_frames={actual_frames} header_frames={frames_header}")
                        
                    logger.info(f"[VOICE_WAV_VALIDATED] bytes={len(audio_data)} duration_ms={duration_ms:.2f} sample_rate={sample_rate} channels={channels} sample_width={sample_width*8}")
            except Exception as e:
                logger.error(f"[VOICE_WAV_ERROR] WAV validation failed: {e}")
                raise HTTPException(status_code=422, detail="Voice input couldn't be processed. Please try again.")

            stats = calculate_wav_stats(audio_data)
            if stats:
                logger.info(f"[VOICE_CAPTURE_DIAGNOSTIC] session_id={conversation_id} utterance_id={utterance_id} mime={audio.content_type} duration_ms={stats['duration_ms']} wav_duration_ms={stats['duration_ms']} sample_rate={stats['sample_rate']} channels={stats['channels']} rms={stats['rms']:.2f} peak={stats['peak']} speech_ratio={stats['speech_ratio']:.2f}% leading_silence_ms={stats['leading_silence_ms']} trailing_silence_ms={stats['trailing_silence_ms']}")
                logger.info(f"[VOICE_AUDIO_STATS] duration_ms={stats['duration_ms']} sample_rate={stats['sample_rate']} channels={stats['channels']} rms={stats['rms']:.2f} peak={stats['peak']} speech_ratio={stats['speech_ratio']:.2f}% leading_silence_ms={stats['leading_silence_ms']} trailing_silence_ms={stats['trailing_silence_ms']}")
                
                # Allow short utterances (like 'Haan', 'Yes') if they have decent peak energy
                # even if the speech ratio is low
                is_short_utterance = stats['duration_ms'] < 1500 and stats['peak'] > 500
                if stats['speech_ratio'] < 2.0 and not is_short_utterance:
                    logger.warning("[VOICE_STT_EMPTY] Audio contains no significant speech activity. Dropping before STT.")
                    logger.info(f"[VOICE_STT_STATE] utterance_id={utterance_id} audio_duration_ms={stats['duration_ms']} speech_ratio={stats['speech_ratio']:.2f} result=ACTUAL_NO_SPEECH latency_ms=0")
                    return {
                        "answer": "",
                        "sources": [],
                        "conversation_id": conversation_id,
                        "transcript": "",
                        "audio_base64": "",
                        "no_speech": True
                    }
        else:
            stderr_out = process.stderr.decode('utf-8', errors='replace') if process.stderr else "None"
            logger.error(f"[VOICE_FFMPEG_ERROR] return_code={process.returncode} stderr={stderr_out}")
            raise HTTPException(status_code=422, detail="Voice input couldn't be processed. Please try again.")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[VOICE_STT_START] FFmpeg error: {e}")
        raise HTTPException(status_code=422, detail="Voice input couldn't be processed. Please try again.")
    
    stt_start_time = time.perf_counter()
    stt_ms = 0
    
    try:
        logger.info(f"[VOICE_STT_START] Calling realtime_stt")
        transcript = await realtime_stt(audio_data, language=lang, encoding="audio/wav")
        stt_ms = (time.perf_counter() - stt_start_time) * 1000
        
        if transcript:
            logger.info(f"[VOICE_STT_RESULT] utterance_id={utterance_id} transcript='{transcript}' language={lang} latency_ms={stt_ms:.2f}")
        else:
            logger.info(f"[VOICE_STT_RESULT] utterance_id={utterance_id} transcript='' language={lang} latency_ms={stt_ms:.2f} status=NO_SPEECH")
            
    except Exception as stt_err:
        stt_ms = (time.perf_counter() - stt_start_time) * 1000
        result_status = "STT_ERROR"
        status_code = 500
        if "timeout" in str(stt_err).lower():
            result_status = "STT_TIMEOUT"
            status_code = 504
            
        logger.error(f"[VOICE_STT_RESULT] utterance_id={utterance_id} transcript='' language={lang} latency_ms={stt_ms:.2f} status={result_status} error='{stt_err}'")
        
        audio_dur = stats['duration_ms'] if stats else 0
        speech_rat = stats['speech_ratio'] if stats else 0
        logger.info(f"[VOICE_STT_STATE] utterance_id={utterance_id} audio_duration_ms={audio_dur} speech_ratio={speech_rat:.2f} result={result_status} latency_ms={stt_ms:.2f}")
        
        raise HTTPException(status_code=status_code, detail="Voice input couldn't be processed. Please try again.")

    if not transcript or not transcript.strip():
        # STT returned empty (likely silence/noise)
        logger.warning(f"[VOICE_STT_EMPTY] STT returned empty transcript for agent {agent_id}")
        
        audio_dur = stats['duration_ms'] if stats else 0
        speech_rat = stats['speech_ratio'] if stats else 0
        logger.info(f"[VOICE_STT_STATE] utterance_id={utterance_id} audio_duration_ms={audio_dur} speech_ratio={speech_rat:.2f} result=ACTUAL_NO_SPEECH latency_ms={stt_ms:.2f}")
        
        return {
            "answer": "",
            "sources": [],
            "conversation_id": conversation_id,
            "transcript": "",
            "audio_base64": "",
            "no_speech": True
        }
        
    audio_dur = stats['duration_ms'] if stats else 0
    speech_rat = stats['speech_ratio'] if stats else 0
    logger.info(f"[VOICE_STT_STATE] utterance_id={utterance_id} audio_duration_ms={audio_dur} speech_ratio={speech_rat:.2f} result=SUCCESS latency_ms={stt_ms:.2f}")

    if not conversation_id:
        logger.info(f"[VOICE_CONVERSATION] event=initialized conversation_id=none agent_id={agent_id} source=voice")
    else:
        logger.info(f"[VOICE_CONVERSATION] event=reused conversation_id={conversation_id} agent_id={agent_id} source=voice")

    # If there's a pending partial transcript from the previous utterance, merge it
    if pending_transcript:
        logger.info(f"[VOICE_PARTIAL_MERGE] first='{pending_transcript}' second='{transcript}' merged='{pending_transcript} {transcript}'")
        transcript = f"{pending_transcript} {transcript}".strip()

    # Incomplete transcript guard
    import re
    INCOMPLETE_PATTERNS = re.compile(r'^(what\s+is|what\s+are|what\s+was|who\s+is|who\s+are|how\s+does|how\s+do|how\s+can|tell\s+me|tell\s+me\s+about|can\s+you|can\s+i|is\s+there|do\s+you|does\s+it|what\s+about|why\s+is|why\s+are|when\s+is|where\s+is|which\s+is|why|how|kya\s+hai|kya\s+hota\s+hai|kya\s+hain|kaise|kaise\s+hai|kitne|kitna|kaun|kaun\s+hai|kahan|kis\s+liye|kyun|batao|bataye|bata)$', re.IGNORECASE)
    COMPLETE_SHORT = re.compile(r'^(hi|hello|yes|no|okay|ok|sure|thanks|thank\s+you|haan|nahi|theek|theek\s+hai|accha|haan\s+ji|namaskar|namaste)$', re.IGNORECASE)
    DANGLING_SUFFIXES = re.compile(r'\b(and|or|but|with|for|about|of|to|is|are|\w+\'s|\w+s\')[\W]*$', re.IGNORECASE)
    
    clean_transcript = re.sub(r'[^a-zA-Z0-9\s]', '', transcript).strip()
    t_words = clean_transcript.split()
    
    is_incomplete = False
    inc_reason = ""
    
    if len(t_words) <= 4 and bool(INCOMPLETE_PATTERNS.match(clean_transcript)) and not bool(COMPLETE_SHORT.match(clean_transcript)):
        is_incomplete = True
        inc_reason = "matched_incomplete_pattern"
    elif bool(DANGLING_SUFFIXES.search(transcript)):
        is_incomplete = True
        inc_reason = "dangling_suffix"
        
    if is_incomplete:
        logger.warning(f"[VOICE_PARTIAL_GUARD] transcript='{transcript}' is_incomplete=true reason='{inc_reason}' continuation_window_ms=2500")
        logger.info(f"[VOICE_PARTIAL_WAIT] pending='{transcript}' session_id={conversation_id} utterance_id={utterance_id}")
        
        return {
            "answer": "",
            "sources": [],
            "conversation_id": conversation_id,
            "transcript": transcript,
            "audio_base64": "",
            "no_speech": False,
            "is_incomplete": True
        }
        
    logger.info(f"[VOICE_PARTIAL_GUARD] transcript='{transcript}' is_incomplete=false reason='complete_utterance'")

    # 1.5 Load real conversation history from DB so intent engine has context for follow-ups
    #     The frontend sends history=[] for voice chat; we must load it server-side.
    voice_history: list = []
    if conversation_id:
        try:
            from services import conversation_service
            raw_msgs = await conversation_service.get_conversation_messages(company_id, conversation_id)
            if raw_msgs:
                # Last 8 messages = 4 turns of context
                raw_msgs = raw_msgs[-8:]
                voice_history = [
                    {"role": m.get("role", "user"), "content": m.get("text", "")}
                    for m in raw_msgs
                    if m.get("text")
                ]
            logger.info(f"[VOICE_HISTORY_TRACE] conversation_id={conversation_id} stored_messages={len(raw_msgs) if raw_msgs else 0} loaded_messages={len(voice_history)} history_turns={len(voice_history)//2} message_roles={[m.get('role') for m in (raw_msgs or [])]}")
            logger.info(f"[VOICE_HISTORY_LOADED] turns={len(voice_history)} conversation_id={conversation_id}")
        except Exception as _hist_err:
            logger.warning(f"[VOICE_CONTEXT_LOAD_FAILED] {_hist_err}")
            voice_history = []

    # Context-aware phonetic repair
    from services import tenant_service
    company = await tenant_service.get_company(company_id)
    cname = company.get("name", "") if company else ""
    
    old_transcript = transcript
    transcript, changed, reason, conf, matched_cand, matched_canon, source = normalize_known_entities(transcript, cname)
                
    logger.info(f"[VOICE_STT_NORMALIZATION] raw='{old_transcript}' normalized='{transcript}' changed={str(changed).lower()} reason={reason} confidence={conf:.2f}")
    if changed:
        logger.info(f"[VOICE_ENTITY_MATCH] candidate='{matched_cand}' canonical='{matched_canon}' confidence={conf:.2f} matched=true source={source}")
    logger.info(f"[VOICE_STT_QUALITY] duration_ms={audio_dur} speech_ratio={speech_rat:.2f} raw_transcript_len={len(old_transcript)} normalized_transcript_len={len(transcript)}")

    logger.info(f"[VOICE_TRANSCRIPT] '{transcript[:80]}' conv={conversation_id}")

    # 3. Detect spoken language from transcript content (not from agent.default_language).
    #    agent.default_language is the configured *fallback* language for TTS;
    #    the user's actual spoken language is inferred from the transcript text.
    from ai.language_detector import detect_language as _voice_detect_lang
    _voice_lang_result = _voice_detect_lang(transcript, voice_history)
    _voice_script = _voice_lang_result.script
    _voice_lang  = _voice_lang_result.lang

    # Map detected language to Sarvam BCP-47 TTS code
    _LANG_TO_TTS = {
        "hindi":     "hi-IN",
        "gujarati":  "gu-IN",
        "marathi":   "mr-IN",
        "bengali":   "bn-IN",
        "tamil":     "ta-IN",
        "telugu":    "te-IN",
        "kannada":   "kn-IN",
        "malayalam": "ml-IN",
        "punjabi":   "pa-IN",
        "urdu":      "ur-IN",
        "english":   "en-IN",
    }
    tts_lang = _LANG_TO_TTS.get(_voice_lang, lang)  # lang = agent default_language as safe fallback
    logger.info(f"[VOICE_LANG_DETECTED] transcript_lang={_voice_lang} script={_voice_script} tts_lang={tts_lang}")

    # 4. Process via existing chat pipeline with real history for context resolution
    req = AgentTestChatRequest(
        message=transcript,
        history=voice_history,
        conversation_id=conversation_id
    )

    ai_start_time = time.perf_counter()
    logger.info(f"[VOICE_AI_START] Sending transcript to chat pipeline conv={conversation_id} history_turns={len(voice_history)}")
    # Re-use exact same logic
    chat_result = await agent_test_chat(
        body=req,
        company_id=company_id,
        agent_id=agent_id,
        ctx=ctx
    )

    ai_ms = (time.perf_counter() - ai_start_time) * 1000
    logger.info(f"[VOICE_AI_SUCCESS] answer_len={len(chat_result.get('answer',''))} conv={chat_result.get('conversation_id')} ai_ms={ai_ms:.2f}")

    answer_text = chat_result.get("answer", "")

    # 5. Text to Speech — use transcript-detected language, not agent default
    tts_bytes = b""
    tts_error_msg = None
    tts_start_time = time.perf_counter()
    
    if answer_text:
        speaker = agent.get("tts_voice", "anushka")
        
        # Step 6: TTS Cache for deterministic fast-path responses
        # We only cache if the answer came from the deterministic fast path, ensuring dynamic RAG answers aren't cached.
        is_deterministic = "Deterministic" in chat_result.get("details", "") or "fast path" in chat_result.get("details", "")
        
        import hashlib
        cache_key = None
        if is_deterministic:
            text_hash = hashlib.md5(answer_text.encode('utf-8')).hexdigest()
            cache_key = f"{company_id}:{tts_lang}:{speaker}:{text_hash}"
            
        from collections import OrderedDict
        global _tts_cache
        if '_tts_cache' not in globals():
            _tts_cache = OrderedDict()
            
        if cache_key and cache_key in _tts_cache:
            tts_bytes = _tts_cache[cache_key]
            _tts_cache.move_to_end(cache_key)
            logger.info(f"[VOICE_TTS_CACHE_HIT] speaker={speaker} lang={tts_lang} text_len={len(answer_text)}")
        else:
            logger.info(f"[VOICE_TTS_START] speaker={speaker} lang={tts_lang} text_len={len(answer_text)} cache_key={cache_key}")
            try:
                tts_bytes = await realtime_tts(text=answer_text, language=tts_lang, speaker=speaker)
                tts_ms = (time.perf_counter() - tts_start_time) * 1000
                if len(tts_bytes) > 0:
                    logger.info(f"[VOICE_TTS_SUCCESS] audio_bytes={len(tts_bytes)} tts_ms={tts_ms:.2f}")
                    if cache_key:
                        _tts_cache[cache_key] = tts_bytes
                        _tts_cache.move_to_end(cache_key)
                        if len(_tts_cache) > 100:
                            _tts_cache.popitem(last=False)
                else:
                    tts_error_msg = "TTS service returned 0 bytes."
                    logger.warning(f"[VOICE_TTS_FAILURE] {tts_error_msg}")
            except Exception as tts_err:
                tts_error_msg = str(tts_err)
                logger.error(f"[VOICE_TTS_FAILURE] TTS failed: {tts_err}")
                tts_bytes = b""

    audio_base64 = base64.b64encode(tts_bytes).decode('utf-8') if tts_bytes else ""

    chat_result["transcript"] = transcript
    chat_result["audio_base64"] = audio_base64
    if tts_error_msg:
        chat_result["audio_error"] = tts_error_msg

    total_ms = (time.perf_counter() - stt_start_time) * 1000
    logger.info(f"[VOICE_AI_TIMING] stt_ms={locals().get('stt_ms', 0):.2f} ai_ms={locals().get('ai_ms', 0):.2f} tts_ms={locals().get('tts_ms', 0):.2f} total_ms={total_ms:.2f}")

    if not chat_result.get("no_speech"):
        incoming_duration = (stats['duration_ms'] / 1000.0) if stats else 0.0
        tts_duration = len(answer_text) / 15.0 if answer_text else 0.0
        
        await usage_service.increment_usage(
            company_id=company_id,
            call_duration_seconds=(incoming_duration + tts_duration),
            stt_calls=1 if transcript else 0,
            tts_calls=1 if answer_text else 0,
            direction="test-voice-chat"
        )

    return chat_result

import json
import asyncio
import base64


from fastapi import WebSocket, WebSocketDisconnect, Path
from core.security import decode_access_token
from core.database import col_users, col_agents
from bson import ObjectId
from modules.sarvam_stt import StreamingAudioPipeline
from modules.sarvam_tts import realtime_tts

# This will be appended to zenaipex/api/v1/agents.py
@router.websocket("/companies/{company_id}/agents/{agent_id}/voice-stream")
async def voice_stream(
    websocket: WebSocket,
    company_id: str = Path(...),
    agent_id: str = Path(...)
):
    await websocket.accept()
    import uuid
    import time
    voice_session_id = uuid.uuid4().hex
    logger.info(f"[VOICE_WS_OPEN] session={voice_session_id} agent={agent_id}")
    
    # 1. Authenticate via first frame
    try:
        config_frame = await asyncio.wait_for(websocket.receive_text(), timeout=5.0)
        config_data = json.loads(config_frame)
        token = config_data.get("token")
        conversation_id = config_data.get("conversation_id")
        
        if not token:
            raise ValueError("No token provided")
            
        user_id = decode_access_token(token)
        if not user_id:
            raise ValueError("Invalid token")
            
        user = await col_users().find_one({"_id": ObjectId(user_id)})
        if not user:
            logger.error("[VOICE_WS_AUTH_FAILURE] User not found")
            raise ValueError("User not found")
            
        logger.info(f"[VOICE_WS_AUTH_SUCCESS] Authenticated user {user_id}")
            
    except Exception as e:
        logger.error(f"WebSocket auth failed: {e}")
        await websocket.close(code=1008, reason="Unauthorized")
        return

    # Verify Agent exists
    agent = await col_agents().find_one({
        "_id": ObjectId(agent_id),
        "company_id": company_id
    })
    
    if not agent:
        await websocket.close(code=1004, reason="Agent not found")
        return
        
    lang = agent.get("default_language", "en-IN")
    speaker = agent.get("tts_voice", "anushka")

    # 2. Pipeline setup
    latest_transcript = ""
    is_processing = False
    processing_task = None
    
    async def on_transcript_ready(transcript: str):
        nonlocal latest_transcript
        latest_transcript = transcript
        await websocket.send_json({"type": "transcript", "text": transcript, "is_final": True})

    async def _process_speech_task():
        nonlocal latest_transcript, is_processing, conversation_id
        is_processing = True
        start_t = time.perf_counter()
        try:
            await websocket.send_json({"type": "state", "state": "thinking"})
            
            # Setup AuthContext manually
            from core.dependencies import AuthContext
            ctx = AuthContext()
            ctx.user = user
            ctx.company_ids = [company_id]
            ctx.is_member = True
            
            # Prepare Request
            from api.v1.agents import AgentTestChatRequest, agent_test_chat
            req = AgentTestChatRequest(
                message=latest_transcript,
                history=[],
                conversation_id=conversation_id
            )
            
            try:
                logger.info(f"[VOICE_AI_TURN_START] Starting agent_test_chat with transcript len={len(latest_transcript)} session={voice_session_id}")
                resp = await agent_test_chat(
                body=req,
                company_id=company_id,
                agent_id=agent_id,
                ctx=ctx
            )
                logger.info(f"[VOICE_AI_TURN_COMPLETE] Finished agent_test_chat session={voice_session_id}")
            except Exception as e:
                logger.error(f"[VOICE_AI_ERROR] session={voice_session_id} err={e}")
                raise
                
            ai_t = time.perf_counter()
            
            conversation_id = resp.get("conversation_id", conversation_id)
            answer = resp.get("answer", "")
            
            await websocket.send_json({
                "type": "ai_text", 
                "text": answer, 
                "conversation_id": conversation_id
            })
            
            # TTS
            from modules.sarvam_tts import realtime_tts_stream
            
            tts_attempts = 0
            tts_success = False
            first_chunk = True
            
            while tts_attempts < 2 and not tts_success:
                tts_attempts += 1
                logger.info(f"[VOICE_TTS_STREAM_START] attempt={tts_attempts}")
                
                if tts_attempts == 1:
                    await websocket.send_json({"type": "state", "state": "speaking"})
                
                try:
                    async for chunk in realtime_tts_stream(text=answer, language=lang, speaker=speaker):
                        if first_chunk:
                            logger.info(f"[VOICE_TTS_FIRST_CHUNK] latency={time.perf_counter() - ai_t:.2f}s")
                            first_chunk = False
                        audio_base64 = base64.b64encode(chunk).decode('utf-8')
                        await websocket.send_json({"type": "ai_audio_pcm", "audio_base64": audio_base64})
                    tts_success = True
                    if tts_attempts > 1:
                        logger.info("[VOICE_TTS_RECOVERY_SUCCESS]")
                except Exception as e:
                    logger.error(f"[VOICE_TTS_ERROR] session={voice_session_id} err={e}")
                    if not first_chunk:
                        # Already played audio, do not retry and risk duplicate speech
                        logger.error("[VOICE_TTS_PROVIDER_DROP] Mid-stream TTS failure. Aborting to avoid duplicates.")
                        break
                    else:
                        logger.warning("[VOICE_TTS_RECOVERY_START] Retrying TTS...")
                        continue
            
            if not tts_success:
                logger.error("[VOICE_TTS_RECOVERY_FAILED] Returning to listening state cleanly.")
                await websocket.send_json({"type": "ai_audio_pcm_done", "error": True})
            else:
                await websocket.send_json({"type": "ai_audio_pcm_done"})
            logger.info(f"[VOICE_TTS_STREAM_END] session={voice_session_id} total_ms={(time.perf_counter()-start_t)*1000:.0f}")
            
        except asyncio.CancelledError:
            logger.info(f"[VOICE_TTS_STREAM_ABORT] session={voice_session_id}")
            raise
        except Exception as e:
            logger.error(f"[VOICE_PIPELINE_ERROR] session={voice_session_id} err={e}")
            await websocket.send_json({"type": "state", "state": "error", "message": str(e)})
        finally:
            is_processing = False
            latest_transcript = ""
            try:
                await pipeline.reset_for_new_turn()
                await websocket.send_json({"type": "state", "state": "listening"})
            except:
                pass

    async def on_speech_end():
        nonlocal latest_transcript, is_processing, processing_task
        if is_processing:
            return
            
        is_processing = True # Block new audio early
        
        # Flush the pipeline and wait for final transcript
        logger.info(f"[VOICE_VAD_END_SPEECH] Fetching final transcript... session={voice_session_id}")
        final_result = await pipeline.force_finalize()
        if final_result and final_result.transcript.strip():
            latest_transcript = final_result.transcript
            
        if not latest_transcript.strip():
            is_processing = False
            return
            
        processing_task = asyncio.create_task(_process_speech_task())

    pipeline = StreamingAudioPipeline(
        language=lang,
        sample_rate=16000,
        on_transcript_ready=on_transcript_ready,
        on_speech_end=on_speech_end
    )
    
    if not await pipeline.start():
        await websocket.close(code=1011, reason="Failed to start STT pipeline")
        return
        
    await websocket.send_json({"type": "state", "state": "listening"})
    
    # 3. Audio Receive Loop
    try:
        audio_recv_count = 0
        audio_recv_last_log_time = 0
        while True:
            msg = await websocket.receive()
            
            if "bytes" in msg:
                data = msg["bytes"]
                now = time.time()
                if audio_recv_count < 3 or now - audio_recv_last_log_time > 2.0:
                    logger.info(f"[VOICE_WS_AUDIO_RECEIVE] bytes={len(data)} session={voice_session_id}")
                    audio_recv_count += 1
                    audio_recv_last_log_time = now
                    
                if not is_processing:
                    await pipeline.process_audio_chunk(data)
            
            elif "text" in msg:
                try:
                    text_data = json.loads(msg["text"])
                    if text_data.get("type") == "ping":
                        await websocket.send_json({"type": "pong"})
                        continue
                    if text_data.get("type") == "barge_in":
                        logger.info("[VOICE_BARGE_IN_SERVER] Received barge-in signal from client")
                        is_processing = False
                        if processing_task and not processing_task.done():
                            processing_task.cancel()
                            logger.info("[VOICE_BARGE_IN] Cancelled backend LLM/TTS task")
                        await pipeline.stt.reset_for_new_turn()
                except json.JSONDecodeError:
                    pass
                    
            elif msg.get("type") == "websocket.disconnect":
                break
                
    except Exception as e:
        logger.error(f"[VOICE_WS_ERROR] session={voice_session_id} err={e}")
    finally:
        logger.info(f"[VOICE_WS_CLEANUP] session={voice_session_id}")
        if processing_task and not processing_task.done():
            processing_task.cancel()
        if pipeline.stt:
            await pipeline.stt.disconnect()
        logger.info(f"[VOICE_WS_CLOSE] session={voice_session_id}")
