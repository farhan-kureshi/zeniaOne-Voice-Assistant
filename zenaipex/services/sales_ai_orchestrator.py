import logging
import time
from bson import ObjectId

from core.database import col_agents, col_companies
from services.conversation_service import add_message, get_conversation_messages
from ai.llm import AgentLLMClient
from ai.rag import get_rag_pipeline
from ai.fast_path import check_deterministic_fast_path
from ai.language_detector import detect_language

logger = logging.getLogger(__name__)

class SalesAIOperator:
    """
    Orchestrates the AI voice pipeline for outbound sales calls (e.g., MockTelephonyProvider).
    Extracts the core business logic (RAG, LLM, DB) away from WebSocket/browser specifics.
    """
    
    @staticmethod
    async def process_text_turn(company_id: str, agent_id: str, conversation_id: str, user_text: str) -> str:
        """
        Process a single simulated/actual user utterance.
        Returns the assistant's response.
        """
        agent = await col_agents().find_one({"_id": ObjectId(agent_id), "company_id": company_id})
        company = await col_companies().find_one({"_id": ObjectId(company_id)})
        
        if not agent or not company:
            logger.error(f"[SALES_AI_OPERATOR] Agent or Company not found for agent_id={agent_id}, company_id={company_id}")
            return "Error: Agent or Company not found."
            
        language = agent.get("default_language", "en-IN")
        
        # 1. Fetch history BEFORE adding current message
        messages = await get_conversation_messages(company_id, conversation_id)
        history = [{"role": m["role"], "content": m.get("text", "")} for m in messages]
        
        # 2. Add user message to conversation
        await add_message(company_id, conversation_id, "user", user_text, language)
        
        # 3. Check fast path / language
        _lang_result = detect_language(user_text, history)
        fast_response = check_deterministic_fast_path(
            message=user_text,
            company=company,
            agent=agent,
            detected_lang=_lang_result.lang,
            detected_script=_lang_result.script
        )
        
        if fast_response:
            response_text = fast_response
            await add_message(company_id, conversation_id, "assistant", response_text, language)
            return response_text
            
        # 4. Normal AI pipeline
        context_docs = None
        rag = get_rag_pipeline(company_id, agent)
        if rag.should_retrieve(user_text):
            context_docs = await rag.retrieve(user_text)
            
        try:
            llm = await AgentLLMClient.create(agent)
            response_text, _ = await llm.generate(
                user_message=user_text,
                conversation_history=history,
                context_docs=context_docs,
                language=language,
                current_date=time.strftime("%A, %B %d, %Y"),
                company_name=company.get("name", "Company")
            )
            if not response_text:
                response_text = "I am sorry, I am having trouble connecting right now."
        except Exception as e:
            logger.error(f"[SALES_AI_OPERATOR] LLM Error: {e}")
            response_text = "I am sorry, an error occurred while processing your request."
            
        # 5. Add assistant response
        await add_message(company_id, conversation_id, "assistant", response_text, language)
        return response_text
