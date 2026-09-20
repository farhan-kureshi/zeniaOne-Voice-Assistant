"""
Zenaipex AI — Tenant-isolated RAG pipeline.

Wraps NamespacedVectorStore + AgentLLMClient into a single
per-call RAG orchestrator. The caller passes the company's
namespace (= company_id) and the agent config at call start.

RAG trigger detection is keyword-based (same as legacy) but the
keyword list can be extended per-agent in future.
"""
import logging
from typing import List, Dict, Any, Optional

from ai.vector_store import NamespacedVectorStore

logger = logging.getLogger(__name__)

# ── RAG Trigger Detection ─────────────────────────────────────────────────────
# Keywords that suggest the user is asking a factual question that benefits
# from knowledge base retrieval. Can be extended per-agent later.

DEFAULT_RAG_KEYWORDS = {
    # Service queries
    "price", "cost", "fee", "charge", "rate",
    "timing", "time", "hours", "open", "close",
    "doctor", "specialist", "department", "service",
    "location", "address", "where", "directions",
    # Language variants
    "நேரம்", "விலை", "மருத்துவர்",            # Tamil
    "समय", "दर", "डॉक्टर",                    # Hindi
    "సమయం", "ధర", "డాక్టర్",                 # Telugu
}


def should_use_rag(query: str, language: str = "en-IN") -> bool:
    """
    Determine if a query should trigger knowledge base retrieval.

    Uses simple keyword matching — fast enough for voice latency budget.
    """
    query_lower = query.lower()
    for keyword in DEFAULT_RAG_KEYWORDS:
        if keyword in query_lower:
            return True
    return False


class TenantRAGPipeline:
    """
    Per-call RAG pipeline with company namespace isolation.

    Instantiated once per call using the agent config loaded at call start.
    Reuses the same NamespacedVectorStore instance throughout the call.

    Example:
        rag = TenantRAGPipeline(
            namespace=company_id,
            agent_doc=agent,
        )
        context = await rag.retrieve(user_query)
        # → context is a list of relevant text chunks
    """

    def __init__(self, namespace: str, agent_doc: Dict[str, Any]):
        """
        Args:
            namespace:  Pinecone namespace = company_id
            agent_doc:  Full Agent document from MongoDB
        """
        if not namespace:
            raise ValueError("namespace required for RAG pipeline")
        self.namespace = namespace
        self.agent = agent_doc
        self._vs: Optional[NamespacedVectorStore] = None

    def _get_vs(self) -> NamespacedVectorStore:
        if self._vs is None:
            self._vs = NamespacedVectorStore(namespace=self.namespace)
        return self._vs

    def rag_enabled(self) -> bool:
        """Returns True if this agent has a knowledge base attached."""
        return bool(self.agent.get("knowledge_base_id"))

    def should_retrieve(self, query: str, language: str = "en-IN") -> bool:
        """Decide if RAG retrieval should be triggered for this query."""
        if not self.rag_enabled():
            return False
        return should_use_rag(query, language)

    def _rerank_and_filter(self, query: str, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Step 8B: Cross-Module RAG Diversity Filter
        Selects final context using semantic score, topic diversity, and uniqueness.
        """
        import re
        import logging
        logger = logging.getLogger(__name__)

        final_k = 5
        seen_signatures = set()
        
        def extract_module(res: dict) -> str:
            text = res.get("text", "")
            m = re.search(r'\[Module:\s*\d*\s*([^\|\]]+)', text)
            if m:
                return m.group(1).strip()
            
            meta = res.get("metadata", {})
            mod = meta.get("module") or meta.get("category") or meta.get("topic")
            if mod: return str(mod)
            source = str(meta.get("source", "")).lower()
            if "payroll" in source: return "Payroll"
            if "attendance" in source: return "Attendance"
            if "recruitment" in source: return "Recruitment"
            if "finance" in source: return "Finance"
            if "leave" in source: return "Leave"
            if "performance" in source: return "Performance"
            if "employee" in source: return "Employees"
            return "General"

        grouped_results = {}
        for res in results:
            module = extract_module(res)
            if module not in grouped_results:
                grouped_results[module] = []
                
            text = res.get("text", "")
            signature = re.sub(r'\W+', '', text.lower())[:150]
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                grouped_results[module].append(res)
                
        diverse_results = []
        remaining_candidates = []
        
        for mod, chunks in grouped_results.items():
            if chunks:
                diverse_results.append(chunks[0])
                remaining_candidates.extend(chunks[1:])
                
        remaining_candidates.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        
        while len(diverse_results) < final_k and remaining_candidates:
            diverse_results.append(remaining_candidates.pop(0))
            
        diverse_results.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        final_results = diverse_results[:final_k]
        
        selected_modules = list(set([extract_module(res) for res in final_results]))
        logger.info(f"[RAG_DIVERSITY_SELECTION] candidates={len(results)} selected={len(final_results)} modules={selected_modules}")
        
        return final_results


    async def _rewrite_query(self, query: str, request_id: str, parent_deadline: Optional[float] = None) -> str:
        """
        Phase 12: Conditional Query Normalization
        Bypasses LLM for simple queries to save latency/tokens.
        Translates/Normalizes Hinglish to Devanagari/English for multilingual embeddings.
        """
        import re
        query_lower = query.lower()
        q_words = set(re.findall(r'\b\w+\b', query_lower))
        
        # 1. Native script detection (Devanagari / Gujarati) -> Direct Embedding
        if re.search(r'[\u0900-\u097F\u0A80-\u0AFF]', query):
            return query
            
        # 2. English / Obvious Product Queries -> Direct Embedding
        hinglish_markers = {"kaise", "kya", "kyu", "kab", "kaha", "karo", "batao", "hai", "su", "chhe", "kem", "isme", "usme", "ye", "wo", "ismein", "ka"}
        if not bool(q_words.intersection(hinglish_markers)):
            # It's either pure English or standard keyword search
            # Pronouns resolution can still be tricky but we bypass for speed
            pronouns = {"it", "this", "that", "these", "those", "they", "them"}
            if not bool(q_words.intersection(pronouns)) or len(q_words) > 3:
                return query

        # 3. Lightweight Hinglish Normalization (Dictionary based)
        # We translate Roman Hindi question words to Devanagari so the multilingual model understands it natively
        norm_map = {
            r'\bkaise\b': 'कैसे',
            r'\bkya\b': 'क्या',
            r'\bkyu\b': 'क्यों',
            r'\bkab\b': 'कब',
            r'\bkaha\b': 'कहाँ',
            r'\bhai\b': 'है',
            r'\bisme\b': 'इसमें',
            r'\bye\b': 'यह',
            r'\bwo\b': 'वह',
            r'\bbatao\b': 'बताओ',
            r'\bsamjhao\b': 'समझाओ',
            r'\bka\b': 'का',
            r'\bki\b': 'की',
            r'\bke\b': 'के',
            r'\bhota\b': 'होता'
        }
        
        normalized = query_lower
        for pattern, replacement in norm_map.items():
            normalized = re.sub(pattern, replacement, normalized)
            
        # If the query is simple, just return the dictionary normalized version
        # It's incredibly fast and works with paraphrase-multilingual natively
        if len(q_words) <= 7:
            logger.info(f"[{request_id}] FAST NORMALIZE: {query} -> {normalized}")
            # Restore capitalization for English proper nouns
            return normalized

        # 4. Fallback: LLM Rewrite for complex/ambiguous Hinglish queries
        logger.info(f"[{request_id}] QUERY REWRITE START\nOriginal: {query}")
        try:
            from ai.llm import AgentLLMClient
            
            rewrite_agent = dict(self.agent)
            rewrite_agent["system_prompt"] = (
                "You are a search query optimizer. The user's query is in Hinglish or Roman Gujarati. "
                "Rewrite the query into a single, clean English search query. "
                "Keep all technical terms like ZeniaHR. Do not answer the question. Only output the rewritten query."
            )
            rewrite_agent["llm_model"] = "llama3-8b-8192"
            rewrite_agent["llm_max_tokens"] = 50
            rewrite_agent["llm_temperature"] = 0.0
            
            async with await AgentLLMClient.create(rewrite_agent, request_id=f"{request_id}-rewrite") as llm:
                if parent_deadline:
                    import time
                    remaining = parent_deadline - time.perf_counter()
                    # Reserve 4s for generation, cap rewrite at 3s
                    sub_budget = min(max(remaining - 4.0, 0.1), 3.0)
                    llm.set_budget(sub_budget)
                else:
                    llm.set_budget(3.0)
                    
                rewritten, _ = await llm.generate(
                    user_message=query,
                    conversation_history=[],
                    language="en-IN",
                    stage="rewrite"
                )
                
            if rewritten and len(rewritten) > 2 and "I am" not in rewritten and not rewritten.startswith("⚠️"):
                logger.info(f"[{request_id}] QUERY REWRITE SUCCESS\nRewritten: {rewritten}")
                return rewritten
        except Exception as e:
            logger.warning(f"[{request_id}] QUERY REWRITE FAILED: {e}")
            
        return normalized


    async def retrieve(
        self,
        query: str,
        top_k: int = 20,  # Fetch a broad candidate set for reranking
        score_threshold: float = 0.15,
        document_ids: Optional[List[str]] = None,
        request_id: str = "REQ-UNKNOWN",
        parent_deadline: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """Phase 12: Production-Hardened Retrieval with Hybrid & Expansion"""
        logger.info(f"[{request_id}] RAG START\nIntent: document_query\nNamespace: {self.namespace}")
        if not self.rag_enabled() and not document_ids:
            logger.info(f"[{request_id}] RAG SKIPPED\nReason: not enabled for agent")
            return []
            
        expanded_query = await self._rewrite_query(query, request_id, parent_deadline=parent_deadline)

        # 1. Centralized Config & Cache
        from ai.config import RAGConfig
        import re
        query_norm = re.sub(r"[^\w\s]", "", expanded_query).strip().lower()
        query_norm = re.sub(r"\s+", " ", query_norm)
        
        # Use existing updated_at from agent document as the deterministic knowledge version
        knowledge_version = str(self.agent.get("updated_at", "v1"))
        cache_key = f"{self.namespace}:{self.agent.get('_id', 'no_agent')}:{knowledge_version}:{query_norm}:{','.join(document_ids) if document_ids else 'all'}"
        
        if RAGConfig.cache_enabled:
            from ai.config import query_cache
            cached = query_cache.get(cache_key)
            if cached and (__import__("time").time() - cached["time"] < RAGConfig.cache_ttl_seconds):
                self._last_candidates = cached["candidates"]
                return cached["results"]

            # Step 6: Negative cache — skip embedding + Pinecone for known-empty queries
            from ai.config import negative_cache
            neg_ts = negative_cache.get(cache_key)
            if neg_ts and (__import__("time").time() - neg_ts < RAGConfig.negative_cache_ttl_seconds):
                logger.info(f"[{request_id}] NEGATIVE_CACHE_HIT query='{query}' cache_age_s={__import__('time').time() - neg_ts:.0f}")
                self._last_candidates = []
                return []

        try:
            vs = self._get_vs()
            filter = None
            if document_ids:
                filter = {"document_id": {"$in": document_ids}}
                
            import asyncio
            start_time = __import__("time").time()
            
            # Step 6: Embedding cache — avoid re-encoding identical queries
            from ai.vector_store import get_cached_embedding, cache_embedding
            cached_emb = get_cached_embedding(expanded_query)
            if cached_emb is not None:
                emb_latency = 0.0
                query_embedding_list = cached_emb
                logger.info(f"[{request_id}] EMBEDDING_CACHE_HIT query='{expanded_query[:50]}'")
            else:
                emb_start = __import__("time").time()
                query_embedding = await asyncio.to_thread(vs._get_model().encode, [expanded_query])
                emb_latency = __import__("time").time() - emb_start
                logger.info(f"[{request_id}] EMBEDDING\nModel: sentence-transformers/all-MiniLM-L6-v2\nLatency: {emb_latency:.2f}s")
                query_embedding_list = query_embedding.tolist()[0]
                cache_embedding(expanded_query, query_embedding_list)
            
            await asyncio.to_thread(vs._get_index)
            
            # 2. Retry Strategy & Candidate Retrieval
            results = []
            pc_start = __import__("time").time()
            for attempt in range(RAGConfig.max_retries):
                try:
                    results = await asyncio.wait_for(
                        asyncio.to_thread(
                            vs.similarity_search,
                            query=expanded_query,
                            top_k=top_k,
                            score_threshold=score_threshold,
                            filter=filter,
                            query_embedding=query_embedding_list
                        ),
                        timeout=RAGConfig.pinecone_timeout_seconds
                    )
                    break
                except asyncio.TimeoutError:
                    logger.warning(f"Pinecone timeout (attempt {attempt+1}/{RAGConfig.max_retries}) ns={self.namespace}")
                    if attempt == RAGConfig.max_retries - 1:
                        raise
                    await asyncio.sleep(RAGConfig.retry_backoff_factor ** attempt)
                except Exception as db_err:
                    logger.warning(f"Pinecone transient error (attempt {attempt+1}): {db_err}")
                    if attempt == RAGConfig.max_retries - 1:
                        raise
                    await asyncio.sleep(RAGConfig.retry_backoff_factor ** attempt)
            
            pc_duration = __import__("time").time() - pc_start
            
            # Phase 4/9/10: Local Reranking and Diversity Filtering
            rerank_start = __import__("time").time()
            final_results = self._rerank_and_filter(expanded_query, results)
            
            # Phase 12: Parent-Child Resolution (only fetch parents if we need broader context)
            final_results = await vs.resolve_parent_chunks(final_results)
            rerank_latency = __import__("time").time() - rerank_start
            
            self._last_candidates = results
            
            if RAGConfig.cache_enabled:
                from ai.config import query_cache
                if final_results:
                    query_cache[cache_key] = {
                        "results": final_results,
                        "candidates": results,
                        "time": start_time,
                        "knowledge_version": knowledge_version
                    }
                else:
                    # Step 6: Store in negative cache
                    from ai.config import negative_cache as neg_c
                    neg_c[cache_key] = start_time
            
            duration = __import__("time").time() - start_time
            logger.info(f"[{request_id}] PINECONE RAG SUMMARY\nOriginal Query: {query}\nExpanded: {expanded_query}\nCandidates Retrieved: {len(results)}\nFinal Ranked Chunks: {len(final_results)}\nRetrieval Latency: {pc_duration:.2f}s\nRerank+Resolve Latency: {rerank_latency:.2f}s\nTotal Latency: {duration:.2f}s")
            
            return final_results
        except Exception as exc:
            logger.error(f"RAG retrieval error (ns={self.namespace}): {exc}")
            return []

    def format_context(self, docs: List[Dict[str, Any]]) -> str:
        """
        Phase 12: Context Assembly
        Format retrieved docs into a context string.
        Groups chunks by module and preserves logical order.
        """
        if not docs:
            return ""
            
        # Group by module number
        grouped_docs = {}
        for doc in docs:
            meta = doc.get("metadata", {})
            mod_num = meta.get("module_number", "General")
            if mod_num not in grouped_docs:
                grouped_docs[mod_num] = []
            grouped_docs[mod_num].append(doc)
            
        parts = []
        for mod_num, mod_docs in grouped_docs.items():
            # Sort within module by page_start or chunk_index if available to maintain logical flow
            mod_docs.sort(key=lambda x: x.get("metadata", {}).get("chunk_index", 0))
            
            parts.append(f"--- Module: {mod_num} ---")
            for doc in mod_docs:
                if doc.get("text"):
                    parts.append(doc["text"])
                    
        return "\n\n".join(parts)


def get_rag_pipeline(namespace: str, agent_doc: Dict[str, Any]) -> TenantRAGPipeline:
    """
    Factory function to get a RAG pipeline for a specific company/agent.

    Args:
        namespace:  company_id (Pinecone namespace)
        agent_doc:  Agent MongoDB document

    Returns:
        TenantRAGPipeline instance
    """
    return TenantRAGPipeline(namespace=namespace, agent_doc=agent_doc)
