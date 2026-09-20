import logging
import json
import re
from typing import List, Dict, Any, Optional
import time

logger = logging.getLogger(__name__)

class MultiHopEngine:
    """
    Phase 11: Advanced RAG Multi-Hop & Dependent Reasoning
    Handles complex queries requiring multiple sequential steps, arithmetic calculation, or comparison.
    """
    
    @staticmethod
    async def resolve_dependent_queries(
        agent_llm,
        rag_pipeline,
        intent_data: Dict[str, Any],
        document_ids: Optional[List[str]] = None,
        request_id: str = "REQ-UNKNOWN"
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], float]:
        """
        Executes sequential dependent queries if `is_multi_hop` is true and `reasoning_type` == 'dependent'.
        Otherwise, runs parallel multi-query execution.
        Returns (context_docs, candidate_pool, retrieval_latency)
        """
        search_queries = intent_data.get("search_queries", [])
        
        # Deduplicate search queries while preserving order
        seen_queries = set()
        deduped_queries = []
        for q in search_queries:
            # Robust normalization: remove punctuation and extra spaces for deduplication
            q_norm = re.sub(r"[^\w\s]", "", q).strip().lower()
            q_norm = re.sub(r"\s+", " ", q_norm)
            
            if q_norm and q_norm not in seen_queries:
                seen_queries.add(q_norm)
                deduped_queries.append(q) # Keep the original query text for Pinecone
        # Enforce budget limits
        from ai.config import RAGConfig
        search_queries = deduped_queries[:RAGConfig.max_search_queries]
        
        is_multi_hop = intent_data.get("is_multi_hop", False)
        reasoning_type = intent_data.get("reasoning_type", "none")
        
        merged_docs = {}
        all_candidates_pool = []
        retrieval_start = time.time()
        
        # 1. Standard Parallel Multi-Query for comparison, multi-part, or simple queries
        if not is_multi_hop or reasoning_type != "dependent":
            if len(search_queries) > 1:
                logger.info(f"[{request_id}] Executing {len(search_queries)} parallel search queries for '{reasoning_type}' intent to maximize coverage.")
            for query in search_queries:
                raw_docs = await rag_pipeline.retrieve(
                    query, 
                    document_ids=document_ids,
                    score_threshold=0.15,
                    top_k=6,
                    request_id=request_id,
                    parent_deadline=getattr(agent_llm, "current_budget_deadline", None)
                )
                if hasattr(rag_pipeline, "_last_candidates"):
                    all_candidates_pool.extend(rag_pipeline._last_candidates)
                    
                MultiHopEngine._merge_results(raw_docs, merged_docs)
                
            retrieval_latency = time.time() - retrieval_start
            all_raw_docs = list(merged_docs.values())
            return all_raw_docs, all_candidates_pool, retrieval_latency
            
        # 2. Sequential Dependent Reasoning (Phase 11)
        # E.g. "What is the highest tier plan and what is its cost?"
        if search_queries:
            # Round 1: Find intermediate entity
            round1_query = search_queries[0]
            r1_docs = await rag_pipeline.retrieve(
                round1_query, 
                document_ids=document_ids,
                score_threshold=0.15,
                top_k=5,
                request_id=request_id,
                parent_deadline=getattr(agent_llm, "current_budget_deadline", None)
            )
            if hasattr(rag_pipeline, "_last_candidates"):
                all_candidates_pool.extend(rag_pipeline._last_candidates)
            MultiHopEngine._merge_results(r1_docs, merged_docs)
            
            # Use LLM to extract the intermediate entity / formulate follow-up query
            context_text = "\n".join([d.get("text", "") for d in r1_docs[:3]])
            dep_prompt = (
                f"You are a routing agent. Original intent queries: {search_queries}.\n"
                f"Based on this retrieved context for step 1:\n{context_text}\n\n"
                f"Identify the intermediate entity asked for in step 1, and formulate a new exact search query for step 2.\n"
                f"If you found the entity 'Pro Plan', the new query should be 'Pro Plan cost'.\n"
                f"Output strictly JSON format: {{\"next_query\": \"...\"}}"
            )
            
            try:
                # Issue 2: Bound rewrite sub-budget
                original_deadline = getattr(agent_llm, "current_budget_deadline", None)
                if original_deadline:
                    remaining = original_deadline - time.perf_counter()
                    # Reserve 4s for generation, cap rewrite at 3s
                    sub_budget = min(max(remaining - 4.0, 0.1), 3.0)
                    agent_llm.current_budget_deadline = time.perf_counter() + sub_budget
                
                try:
                    # Lightweight internal LLM call (only triggered for dependent logic)
                    response, _ = await agent_llm.generate(
                        user_message=dep_prompt,
                        conversation_history=[],
                        context_docs=None,
                        stage="rewrite"
                    )
                finally:
                    if original_deadline:
                        agent_llm.current_budget_deadline = original_deadline
                if response:
                    parsed = json.loads(re.sub(r'```json|```', '', response).strip())
                    next_query = parsed.get("next_query")
                    if next_query:
                        # Round 2: Fetch using the newly resolved intermediate entity
                        r2_docs = await rag_pipeline.retrieve(
                            next_query, 
                            document_ids=document_ids,
                            score_threshold=0.15,
                            top_k=6,
                            request_id=request_id,
                            parent_deadline=getattr(agent_llm, "current_budget_deadline", None)
                        )
                        if hasattr(rag_pipeline, "_last_candidates"):
                            all_candidates_pool.extend(rag_pipeline._last_candidates)
                        MultiHopEngine._merge_results(r2_docs, merged_docs)
            except Exception as e:
                logger.warning(f"Dependent multi-hop resolution failed, falling back to original queries: {e}")
                # Fallback to remaining original queries
                for query in search_queries[1:]:
                    r2_docs = await rag_pipeline.retrieve(query, document_ids=document_ids, top_k=6, request_id=request_id, parent_deadline=getattr(agent_llm, "current_budget_deadline", None))
                    MultiHopEngine._merge_results(r2_docs, merged_docs)

        all_raw_docs = list(merged_docs.values())
        retrieval_latency = time.time() - retrieval_start
        return all_raw_docs, all_candidates_pool, retrieval_latency

    @staticmethod
    def _merge_results(raw_docs: List[Dict[str, Any]], merged_docs: Dict[str, Any]):
        for doc in raw_docs:
            text = doc.get("text", "")
            signature = re.sub(r'\W+', '', text.lower())[:150]
            if signature in merged_docs:
                current_score = merged_docs[signature].get("rerank_score", merged_docs[signature].get("score", 0))
                merged_docs[signature]["rerank_score"] = current_score + 0.1
            else:
                merged_docs[signature] = doc
