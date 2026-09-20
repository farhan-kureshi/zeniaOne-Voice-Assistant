import time
import logging
from typing import List, Dict, Any
from collections import defaultdict

logger = logging.getLogger(__name__)

class ContextAssembler:
    """
    Phase 10: Advanced RAG Context Assembly.
    Groups fragmented chunks back into coherent structural order.
    """
    
    @staticmethod
    def assemble(
        selected_chunks: List[Dict[str, Any]], 
        all_candidates: List[Dict[str, Any]] = None,
        vector_store = None,
        request_id: str = "REQ-UNKNOWN"
    ) -> List[Dict[str, Any]]:
        """
        Assembles chunks by document and chunk_index to restore logical order.
        Optionally pulls in neighboring chunks from the wider candidate pool if needed.
        """
        start_time = time.time()
        
        # 1. Group selected chunks by document_id and section
        docs_group = defaultdict(list)
        
        # Track selected indices to avoid duplicates and help neighbor expansion
        selected_signatures = set()
        for chunk in selected_chunks:
            meta = chunk.get("metadata", {})
            doc_id = meta.get("document_id", "unknown")
            docs_group[doc_id].append(chunk)
            selected_signatures.add(chunk.get("id", ""))
            
        assembled_context = []
        neighbors_added = 0
        
        # 2. Sort and Assemble per Document
        for doc_id, chunks in docs_group.items():
            # Sort chunks by their original sequential order in the document
            chunks.sort(key=lambda x: int(x.get("metadata", {}).get("chunk_index", 0)))
            
            # 3. Neighbor Expansion & Structural merging
            # We look at all_candidates to see if a direct neighbor is available to complete a thought
            expanded_chunks = []
            for i, chunk in enumerate(chunks):
                meta = chunk.get("metadata", {})
                idx = int(meta.get("chunk_index", -1))
                
                # If we have the full candidate pool, look for idx - 1 or idx + 1
                if all_candidates and idx >= 0:
                    for cand in all_candidates:
                        cand_meta = cand.get("metadata", {})
                        cand_doc = cand_meta.get("document_id")
                        cand_idx = int(cand_meta.get("chunk_index", -2))
                        cand_id = cand.get("id", "")
                        
                        if cand_doc == doc_id and cand_id not in selected_signatures:
                            # If it's the immediately preceding or succeeding chunk, pull it in for context
                            if cand_idx == idx - 1 or cand_idx == idx + 1:
                                expanded_chunks.append(cand)
                                selected_signatures.add(cand_id)
                                neighbors_added += 1
                                
                expanded_chunks.append(chunk)

                # 4. Deep Structural Neighbor Expansion
                chunk_type = meta.get("chunk_type", "")
                is_structural_parent = chunk_type in ["heading", "section-heading", "table", "visual_summary"]
                
                has_next = any(
                    int(c.get("metadata", {}).get("chunk_index", -2)) == idx + 1 
                    for c in expanded_chunks
                )
                
                if is_structural_parent and not has_next and vector_store and idx >= 0:
                    try:
                        resp = vector_store.similarity_search(
                            query=" ",
                            top_k=1,
                            score_threshold=-1.0,
                            filter={"document_id": doc_id, "chunk_index": idx + 1}
                        )
                        if resp:
                            fetched_chunk = resp[0]
                            match_id = fetched_chunk.get("id", "")
                            if match_id not in selected_signatures:
                                expanded_chunks.append(fetched_chunk)
                                selected_signatures.add(match_id)
                                neighbors_added += 1
                                logger.info(f"[{request_id}] ContextAssembler fetched missing neighbor {idx + 1} for heading {idx}")
                    except Exception as e:
                        logger.warning(f"[{request_id}] ContextAssembler failed to fetch neighbor {idx + 1}: {e}")
                        
            # Re-sort after adding neighbors
            expanded_chunks.sort(key=lambda x: int(x.get("metadata", {}).get("chunk_index", 0)))
            
            # Format the output to preserve section headers and table structure
            for chunk in expanded_chunks:
                meta = chunk.get("metadata", {})
                section = meta.get("section", "General")
                filename = meta.get("source") or meta.get("document_id") or "Unnamed Source"
                text = chunk.get("text", "")
                
                # Prepend section heading if available to maintain structural hierarchy
                formatted_text = f"--- Document: {filename} | Section: {section} ---\n{text}"
                
                assembled_context.append({
                    "text": formatted_text,
                    "score": chunk.get("rerank_score", chunk.get("score", 0.0)),
                    "source": filename,
                    "metadata": meta
                })
                
        assembly_duration = time.time() - start_time
        logger.info(f"[{request_id}] Context Assembly complete in {assembly_duration:.3f}s. Neighbors added: {neighbors_added}. Final chunks: {len(assembled_context)}")
        
        return assembled_context
