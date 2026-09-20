"""
Phase 12: Production-Hardened Centralized Configuration
Step 6: Added negative cache + namespace invalidation
"""

class RAGConfig:
    # 1. Timeout & Limits
    pinecone_timeout_seconds = 4.0
    llm_generation_timeout = 20.0
    
    # 2. Retry Logic
    max_retries = 2
    retry_backoff_factor = 2.0
    
    # 3. Context & Limits
    max_multi_hop_steps = 2
    max_context_chunks = 12
    max_retrieval_candidates = 20
    max_pinecone_calls = 3
    max_search_queries = 3
    
    # 4. Caching
    cache_enabled = True
    cache_ttl_seconds = 3600  # 1 hour
    negative_cache_ttl_seconds = 300  # 5 minutes — short enough to pick up new docs

# In-memory simple query cache for Phase 12 
# (In production, replace with Redis for scale)
query_cache = {}

# Step 6: Negative cache for queries that returned 0 results
# Key format matches query_cache. Value = timestamp of when cached.
negative_cache = {}

def invalidate_document_cache(document_id: str):
    """
    Phase 12: Cache invalidation. 
    Removes any cached query results that might have contained the updated document.
    Also clears negative cache entries so new docs are discoverable immediately.
    """
    global query_cache, negative_cache
    keys_to_delete = []
    for k in query_cache.keys():
        if "all" in k or document_id in k:
            keys_to_delete.append(k)
    for k in keys_to_delete:
        del query_cache[k]
    
    # Also clear matching negative cache entries
    neg_keys_to_delete = []
    for k in negative_cache.keys():
        if "all" in k or document_id in k:
            neg_keys_to_delete.append(k)
    for k in neg_keys_to_delete:
        del negative_cache[k]


def invalidate_namespace_cache(namespace: str):
    """
    Step 6: Clear ALL cache entries for a company namespace.
    Called when agent config changes (e.g., knowledge base reassignment).
    """
    global query_cache, negative_cache
    query_cache = {k: v for k, v in query_cache.items() if not k.startswith(f"{namespace}:")}
    negative_cache = {k: v for k, v in negative_cache.items() if not k.startswith(f"{namespace}:")}

