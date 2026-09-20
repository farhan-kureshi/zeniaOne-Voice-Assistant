"""
LLM Client Module
Provides the LLM interface for Sarvam-105B with Pinecone RAG support.
Also contains routing stubs for Gemini and OpenAI-compatible endpoints.
"""
import requests
import time
from typing import List, Dict, Any, Optional
import config

# Global timing metrics storage for LLM operations
_llm_timing_metrics = {
    'llm_api_time': 0.0,
    'llm_total_time': 0.0,
}

def get_llm_timing_metrics() -> Dict[str, float]:
    """Get the current timing metrics for LLM operations."""
    return _llm_timing_metrics.copy()

def reset_llm_timing_metrics():
    """Reset timing metrics for a new conversation turn."""
    global _llm_timing_metrics
    _llm_timing_metrics = {'llm_api_time': 0.0, 'llm_total_time': 0.0}


class LLMClient:
    """
    Generic LLM client that works with HTTP-based LLM APIs.
    Designed to work with Gemini, OpenAI-compatible endpoints, or similar REST APIs.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        model: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None
    ):
        """
        Initialize LLM client.
        
        Args:
            api_key: LLM API key (defaults to config)
            api_url: LLM API base URL (defaults to config)
            model: Model name (defaults to config)
            max_tokens: Maximum tokens in response (defaults to config)
            temperature: Temperature for generation (defaults to config)
            top_p: Top-p sampling (defaults to config)
        """
        self.api_key = api_key or config.LLM_API_KEY
        self.api_url = api_url or config.LLM_API_URL
        self.model = model or config.LLM_MODEL
        self.max_tokens = max_tokens or config.LLM_MAX_TOKENS
        self.temperature = temperature or config.LLM_TEMPERATURE
        self.top_p = top_p or config.LLM_TOP_P
        
        if not self.api_key:
            raise ValueError("LLM_API_KEY must be set in environment or config")
    
    def _format_messages_for_api(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        user_message: str,
        context_docs: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, str]]:
        """
        Format messages for the LLM API.
        
        Args:
            system_prompt: System instructions
            conversation_history: List of previous messages
            user_message: Current user message
            context_docs: Retrieved documents for RAG
        
        Returns:
            Formatted messages list
        """
        messages = []
        
        # Add system prompt with RAG context if available
        system_content = system_prompt
        
        if context_docs:
            context_text = "\n\n".join([
                f"[Context {i+1}]: {doc.get('text', '')}"
                for i, doc in enumerate(context_docs[:2])  # Top 2 docs
            ])
            system_content += f"\n\nRelevant knowledge base context:\n{context_text}"
        
        messages.append({
            "role": "system",
            "content": system_content
        })
        
        # Add conversation history (limited by MAX_CONVERSATION_HISTORY)
        max_history = config.MAX_CONVERSATION_HISTORY
        recent_history = conversation_history[-max_history:] if len(conversation_history) > max_history else conversation_history
        
        for msg in recent_history:
            messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        
        # Add current user message
        messages.append({
            "role": "user",
            "content": user_message
        })
        
        return messages
    
    def _call_gemini_api(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """
        Call Google Gemini API.
        
        Args:
            messages: Formatted messages
        
        Returns:
            Generated response text or None on error
        """
        try:
            # Gemini API format
            endpoint = f"{self.api_url}/models/{self.model}:generateContent"
            
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key
            }
            
            # Convert messages to Gemini format
            contents = []
            system_instruction = None
            
            for msg in messages:
                if msg["role"] == "system":
                    system_instruction = msg["content"]
                elif msg["role"] == "user":
                    contents.append({
                        "role": "user",
                        "parts": [{"text": msg["content"]}]
                    })
                elif msg["role"] == "assistant":
                    contents.append({
                        "role": "model",
                        "parts": [{"text": msg["content"]}]
                    })
            
            payload = {
                "contents": contents,
                "generationConfig": {
                    "temperature": self.temperature,
                    "topP": self.top_p,
                    "maxOutputTokens": self.max_tokens,
                }
            }
            
            if system_instruction:
                payload["systemInstruction"] = {
                    "parts": [{"text": system_instruction}]
                }
            
            # ⏱️ TIMING: Gemini API call
            llm_api_start = time.perf_counter()
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=30
            )
            llm_api_time = time.perf_counter() - llm_api_start
            _llm_timing_metrics['llm_api_time'] = llm_api_time
            print(f"⏱️ Gemini API call: {llm_api_time:.3f}s")
            
            # Handle rate limit specifically
            if response.status_code == 429:
                print(f"⚠️ Gemini API rate limit (429). Response: {response.text[:200]}")
                return None
            
            response.raise_for_status()
            
            result = response.json()
            
            # Extract text from Gemini response
            if "candidates" in result and len(result["candidates"]) > 0:
                candidate = result["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"]:
                    parts = candidate["content"]["parts"]
                    if len(parts) > 0 and "text" in parts[0]:
                        return parts[0]["text"]
            
            print(f"⚠️ Unexpected Gemini response format: {result}")
            return None
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error calling Gemini API: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Response: {e.response.text[:300]}")
            return None
    
    def _call_openai_compatible_api(self, messages: List[Dict[str, str]]) -> Optional[str]:
        """
        Call OpenAI-compatible API (OpenAI, Azure OpenAI, Groq, local LLMs, etc.).
        
        Args:
            messages: Formatted messages
        
        Returns:
            Generated response text or None on error
        """
        try:
            endpoint = f"{self.api_url}/chat/completions"
            
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p
            }
            
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            
            # Extract text from OpenAI-style response
            if "choices" in result and len(result["choices"]) > 0:
                return result["choices"][0]["message"]["content"]
            
            return None
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error calling OpenAI-compatible API: {e}")
            if hasattr(e, 'response') and e.response is not None:
                print(f"   Status: {e.response.status_code}")
                print(f"   Response: {e.response.text[:500]}")
            return None
    
    def _call_sarvam_api(self, messages: List[Dict[str, str]], language: str = "en-IN") -> Optional[str]:
        """
        Call Sarvam AI LLM API (sarvam-m model).
        Optimized for Indian languages.
        
        Args:
            messages: Formatted messages
            language: Language code for response (e.g., 'ta-IN', 'hi-IN')
        
        Returns:
            Generated response text or None on error
        """
        try:
            endpoint = f"{self.api_url}/chat/completions"
            
            # Sarvam uses api-subscription-key header
            headers = {
                "Content-Type": "application/json",
                "api-subscription-key": self.api_key
            }
            
            payload = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
                "temperature": self.temperature,
                "top_p": self.top_p
            }
            
            print(f"🧠 Calling Sarvam-105B LLM: {endpoint}")
            print(f"📝 Messages count: {len(messages)} (system + {len(messages)-1} conversation)")
            
            # ⏱️ TIMING: Sarvam LLM API call
            llm_api_start = time.perf_counter()
            response = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=30
            )
            llm_api_time = time.perf_counter() - llm_api_start
            _llm_timing_metrics['llm_api_time'] = llm_api_time
            print(f"⏱️ Sarvam LLM API call: {llm_api_time:.3f}s")
            
            if response.status_code != 200:
                print(f"❌ Sarvam LLM error: {response.status_code} - {response.text[:200]}")
                return None
            
            result = response.json()
            
            # Extract text from response
            if "choices" in result and len(result["choices"]) > 0:
                content = result["choices"][0]["message"].get("content")
                if content is not None:
                    print(f"✅ Sarvam-105B response received ({len(content)} chars)")
                    return content
                else:
                    print("⚠️ Sarvam-105B response content was None")
                    return None
            
            return None
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Error calling Sarvam LLM API: {e}")
            return None
    
    def generate_reply(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        context_docs: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        language: str = "en-IN"
    ) -> Optional[str]:
        """
        Generate a reply using the LLM with optional RAG context.
        
        Args:
            user_message: Current user message
            conversation_history: Previous conversation messages
            context_docs: Retrieved documents for RAG
            system_prompt: Custom system prompt (defaults to hospital booking prompt)
            language: Language code for response (e.g., 'ta-IN', 'hi-IN', 'en-IN')
        
        Returns:
            Generated response text or None on error
        """
        if conversation_history is None:
            conversation_history = []
        
        if system_prompt is None:
            system_prompt = config.HOSPITAL_SYSTEM_PROMPT
        
        # Format messages
        messages = self._format_messages_for_api(
            system_prompt,
            conversation_history,
            user_message,
            context_docs
        )
        
        print(f"🗣️ LLM will respond in: {language}")
        
        # Detect API type based on URL and call appropriate method
        if "generativelanguage.googleapis.com" in self.api_url or "gemini" in self.model.lower():
            return self._call_gemini_api(messages)
        elif "api.sarvam.ai" in self.api_url or "sarvam" in self.model.lower():
            return self._call_sarvam_api(messages, language)  # Pass language to Sarvam
        else:
            # Default to OpenAI-compatible format (Groq, OpenAI, etc.)
            return self._call_openai_compatible_api(messages)
    
    def detect_crisis(self, text: str) -> bool:
        """
        Detect if the text contains crisis keywords.
        
        Args:
            text: Text to analyze
        
        Returns:
            True if crisis keywords detected, False otherwise
        """
        if not config.ENABLE_CRISIS_DETECTION:
            return False
        
        text_lower = text.lower()
        
        for keyword in config.CRISIS_KEYWORDS:
            if keyword.strip().lower() in text_lower:
                return True
        
        return False


# Convenience functions for backward compatibility
def get_chatbot_response(
    query: str,
    user_phone: str,
    history: Optional[List[Dict[str, str]]] = None,
    user_language: str = "en-IN",
    user_language_name: str = "English"
) -> str:
    """
    Legacy function for backward compatibility.
    Generates chatbot response without RAG.
    
    Args:
        query: User query
        user_phone: User phone number (for logging)
        history: Conversation history
        user_language: User's detected language code for error messages
        user_language_name: Human readable language name for LLM prompt
    
    Returns:
        Generated response text
    """
    # Error messages in different languages
    error_messages = {
        'ta-IN': 'மன்னிக்கவும், தொழில்நுட்ப சிக்கல். மீண்டும் முயற்சிக்கவும்.',
        'hi-IN': 'क्षमा करें, तकनीकी समस्या है। कृपया फिर से कोशिश करें।',
        'te-IN': 'క్షమించండి, సాంకేతిక సమస్య. దయచేసి మళ్ళీ ప్రయత్నించండి.',
        'en-IN': "Sorry, I'm having trouble right now. Please try again."
    }
    
    default_error = error_messages.get(user_language, error_messages['en-IN'])
    
    try:
        llm_client = LLMClient()
        
        # Detect crisis situations
        if llm_client.detect_crisis(query):
            return (
                "I hear that you're going through a really difficult time. "
                "Please reach out to a crisis helpline immediately: "
                "988 (US Suicide & Crisis Lifeline) or your local emergency services. "
                "You don't have to face this alone."
            )
        
        # Get current date for the system prompt
        from datetime import datetime
        current_date = datetime.now().strftime("%d %B %Y")  # e.g., "14 December 2025"
        
        # Inject user's language AND current date into system prompt
        system_prompt = config.HOSPITAL_SYSTEM_PROMPT.replace("{user_language}", user_language_name)
        system_prompt = system_prompt.replace("{current_date}", current_date)
        
        # Add VERY STRONG language instruction - LLM tends to ignore weak hints
        if user_language_name != "English":
            system_prompt += f"""

⚠️ CRITICAL LANGUAGE REQUIREMENT ⚠️
You MUST respond ONLY in {user_language_name}. 
- If user speaks in {user_language_name}, respond in {user_language_name}
- If user speaks in English but language is set to {user_language_name}, STILL respond in {user_language_name}
- NEVER respond in English when language is {user_language_name}
- This is the user's explicit preference. Respect it completely.
"""
        
        print(f"🎯 System prompt language: {user_language_name} ({user_language})")
        
        # ⏱️ TIMING: Total LLM processing (including retries)
        llm_total_start = time.perf_counter()
        
        # Try to get response with retry
        for attempt in range(3):  # Retry up to 3 times
            response = llm_client.generate_reply(
                user_message=query,
                conversation_history=history or [],
                system_prompt=system_prompt,
                language=user_language  # Pass language code to Sarvam API
            )
            
            if response:
                llm_total_time = time.perf_counter() - llm_total_start
                _llm_timing_metrics['llm_total_time'] = llm_total_time
                print(f"⏱️ LLM total time (incl. retries): {llm_total_time:.3f}s")
                return response
            
            if attempt < 2:  # Don't sleep on last attempt
                wait_time = 0.5  # ⚡ Fast retry - reduced from 2-4s
                print(f"⏳ LLM retry attempt {attempt + 2}/3 after {wait_time}s...")
                time.sleep(wait_time)
        
        llm_total_time = time.perf_counter() - llm_total_start
        _llm_timing_metrics['llm_total_time'] = llm_total_time
        return default_error
        
    except Exception as e:
        print(f"Error in get_chatbot_response: {e}")
        return default_error


def get_chatbot_response_with_rag(
    query: str,
    user_phone: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    retrieved_docs: Optional[List[Dict[str, Any]]] = None
) -> str:
    """
    Generate chatbot response with RAG (Retrieval Augmented Generation).
    
    Args:
        query: User query
        user_phone: User phone number (for logging)
        conversation_history: Previous conversation messages
        retrieved_docs: Documents retrieved from Pinecone
    
    Returns:
        Generated response text
    """
    try:
        llm_client = LLMClient()
        
        # Detect crisis situations
        if llm_client.detect_crisis(query):
            return (
                "I hear that you're going through a really difficult time. "
                "Please reach out to a crisis helpline immediately: "
                "988 (US Suicide & Crisis Lifeline) or your local emergency services. "
                "You don't have to face this alone."
            )
        
        response = llm_client.generate_reply(
            user_message=query,
            conversation_history=conversation_history or [],
            context_docs=retrieved_docs
        )
        
        return response or "I'm sorry, I'm having trouble responding right now. Please try again."
        
    except Exception as e:
        print(f"Error in get_chatbot_response_with_rag: {e}")
        return "I apologize, but I'm experiencing technical difficulties. Please try again in a moment."



