"""
Zenaipex AI — Namespaced Vector Store.

Wraps the legacy VectorStore with Pinecone namespace isolation.
Each company's vectors are fully isolated in their own namespace (= company_id).

This is the MULTI-TENANT replacement for modules/vector_store.py.
The legacy module is left untouched and still serves RK Hospital.
"""
import time
import asyncio
import logging
from typing import List, Dict, Any, Optional
from collections import OrderedDict
from pinecone import Pinecone, ServerlessSpec
from sentence_transformers import SentenceTransformer

from core.config import settings

logger = logging.getLogger(__name__)

# ── Singleton embedding model ─────────────────────────────────────────────────
# Shared across all namespaces — model is the same, only namespace differs

import threading

_embedding_model: Optional[SentenceTransformer] = None
_embedding_lock = threading.Lock()

def _get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        with _embedding_lock:
            if _embedding_model is None:
                logger.info(f"[EMBEDDING_MODEL_INIT] status=loading model={settings.embedding_model}")
                start_time = time.perf_counter()
                
                try:
                    # local_files_only=True prevents the 90+ second hang from HuggingFace HEAD requests
                    _embedding_model = SentenceTransformer(settings.embedding_model, local_files_only=True)
                except Exception as e:
                    logger.error(f"[EMBEDDING_MODEL_ERROR] Failed to load model locally: {str(e)}. "
                                 f"Ensure the model is downloaded to the HuggingFace cache.")
                    raise RuntimeError(f"Embedding model not available locally: {str(e)}")
                    
                latency_ms = (time.perf_counter() - start_time) * 1000
                logger.info(f"[EMBEDDING_MODEL_READY] model={settings.embedding_model} device={_embedding_model.device} latency_ms={latency_ms:.2f}")
    return _embedding_model


# ── Step 6: Bounded Embedding Cache ───────────────────────────────────────────
# Caches query→embedding mappings to avoid re-encoding identical queries.
# Embeddings are deterministic for the same model+text, so no TTL needed.
# Bounded at 200 entries with LRU eviction.

_EMBEDDING_CACHE_MAX = 200
_embedding_cache: OrderedDict = OrderedDict()

def get_cached_embedding(text: str) -> Optional[List[float]]:
    """Check if embedding for this text is cached. Returns None on miss."""
    if text in _embedding_cache:
        _embedding_cache.move_to_end(text)
        return _embedding_cache[text]
    return None

def cache_embedding(text: str, embedding: List[float]):
    """Store embedding in bounded LRU cache."""
    _embedding_cache[text] = embedding
    _embedding_cache.move_to_end(text)
    while len(_embedding_cache) > _EMBEDDING_CACHE_MAX:
        _embedding_cache.popitem(last=False)



# ── Pinecone client singleton ─────────────────────────────────────────────────

_pinecone_client: Optional[Pinecone] = None
_pinecone_index = None
_pinecone_lock = threading.Lock()

def _get_pinecone_index():
    global _pinecone_client, _pinecone_index

    if _pinecone_index is not None:
        return _pinecone_index

    with _pinecone_lock:
        if _pinecone_index is not None:
            return _pinecone_index

        if not settings.pinecone_api_key:
            raise RuntimeError("PINECONE_API_KEY not configured")

        _pinecone_client = Pinecone(api_key=settings.pinecone_api_key)

        # Create index if not exists
        existing = [i["name"] for i in _pinecone_client.list_indexes()]
        if settings.pinecone_index_name not in existing:
            logger.info(f"Creating Pinecone index: {settings.pinecone_index_name}")
            _pinecone_client.create_index(
                name=settings.pinecone_index_name,
                dimension=settings.pinecone_dimension,
                metric="cosine",
                spec=ServerlessSpec(
                    cloud=settings.pinecone_cloud,
                    region=settings.pinecone_region,
                ),
            )
            # Wait for readiness
            while not _pinecone_client.describe_index(settings.pinecone_index_name).status["ready"]:
                time.sleep(1)
            logger.info("✅ Pinecone index ready")

        _pinecone_index = _pinecone_client.Index(settings.pinecone_index_name)
        logger.info(f"[PINECONE_READY] Connected to index={settings.pinecone_index_name}")
        return _pinecone_index


# ── Namespaced Vector Store ───────────────────────────────────────────────────

class NamespacedVectorStore:
    """
    Pinecone vector store scoped to a single company namespace.

    ISOLATION GUARANTEE:
    - Every upsert writes ONLY to self.namespace
    - Every query reads ONLY from self.namespace
    - Vectors from other companies are INVISIBLE

    Usage:
        vs = NamespacedVectorStore(namespace=company_id)
        results = vs.similarity_search(query, top_k=3)
    """

    def __init__(self, namespace: str):
        """
        Args:
            namespace: The Pinecone namespace (= company_id string).
                       All reads and writes are isolated to this namespace.
        """
        if not namespace:
            raise ValueError("namespace is required — cannot create a global VectorStore")
        self.namespace = namespace
        self._index = None
        self._model = None

    def _get_index(self):
        if self._index is None:
            self._index = _get_pinecone_index()
        return self._index

    def _get_model(self) -> SentenceTransformer:
        if self._model is None:
            self._model = _get_embedding_model()
        return self._model

    def generate_embeddings(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """Embed a list of text strings using the shared embedding model in batches."""
        model = self._get_model()
        
        # Prevent empty or whitespace-only chunks from causing issues
        safe_texts = [t.strip() if t and t.strip() else "empty" for t in texts]
        
        # encode supports batch_size to keep memory usage safe
        embeddings = model.encode(safe_texts, batch_size=batch_size, show_progress_bar=False)
        
        # Dimension validation check against settings
        if len(embeddings) > 0 and len(embeddings[0]) != settings.pinecone_dimension:
            logger.error(f"Dimension mismatch: Model output {len(embeddings[0])}, expected {settings.pinecone_dimension}")
            raise ValueError(f"Embedding dimension mismatch. Expected {settings.pinecone_dimension}")
            
        return embeddings.tolist()

    async def upsert_vectors(
        self,
        vectors: List[Dict[str, Any]],
        batch_size: int = 100,
    ) -> None:
        """
        Upsert vectors into THIS COMPANY'S namespace.

        Args:
            vectors: List of {"id": str, "values": List[float], "metadata": dict}
            batch_size: Pinecone upsert batch size
        """
        index = self._get_index()
        logger.info(f"Upserting {len(vectors)} vectors to namespace={self.namespace}")

        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            # CRITICAL: namespace parameter ensures isolation
            index.upsert(vectors=batch, namespace=self.namespace)

        logger.info(f"✅ Upsert complete: {len(vectors)} vectors → namespace={self.namespace}")

    def similarity_search(
        self,
        query: str,
        top_k: int = 3,
        score_threshold: float = 0.3,
        filter: Optional[Dict[str, Any]] = None,
        query_embedding: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search THIS COMPANY'S knowledge base only.

        Args:
            query:           Natural language query
            top_k:           Number of results to return
            score_threshold: Minimum cosine similarity score
            filter:          Optional Pinecone metadata filter dict
            query_embedding: Optional pre-computed embedding to avoid redundant ML encoding

        Returns:
            List of {"id", "score", "text", "source", "document_id"}
        """
        index = self._get_index()

        # Embed query if not provided
        if not query_embedding:
            model = self._get_model()
            query_embedding = model.encode([query]).tolist()[0]

        # CRITICAL: namespace parameter — only searches this company's vectors
        results = index.query(
            vector=query_embedding,
            top_k=top_k,
            namespace=self.namespace,     # ← TENANT ISOLATION
            include_metadata=True,
            filter=filter,
        )

        formatted = []
        for match in results.get("matches", []):
            score = match.get("score", 0.0)
            if score >= score_threshold:
                metadata = match.get("metadata", {})
                formatted.append({
                    "id": match["id"],
                    "score": score,
                    "text": metadata.get("text", ""),
                    "source": metadata.get("source", ""),
                    "document_id": metadata.get("document_id", ""),
                    "metadata": metadata,
                })

        return formatted

    async def delete_vectors(self, vector_ids: List[str]) -> None:
        """Delete specific vectors from this company's namespace."""
        if not vector_ids:
            return
        index = self._get_index()
        # CRITICAL: namespace parameter — only deletes from this company's namespace
        index.delete(ids=vector_ids, namespace=self.namespace)
        logger.info(f"Deleted {len(vector_ids)} vectors from namespace={self.namespace}")

    def get_stats(self) -> Dict[str, Any]:
        """Return Pinecone index stats for this namespace."""
        index = self._get_index()
        stats = index.describe_index_stats()
        namespace_stats = stats.get("namespaces", {}).get(self.namespace, {})
        return {
            "namespace": self.namespace,
            "vector_count": namespace_stats.get("vector_count", 0),
            "total_index_vectors": stats.get("total_vector_count", 0),
        }

    async def fetch_vectors(self, vector_ids: List[str]) -> Dict[str, Any]:
        """Fetch vectors by ID from this company's namespace in safe batches to prevent HTTP 414."""
        if not vector_ids:
            return {}
        index = self._get_index()
        results = {}
        
        # Deduplicate to prevent duplicate IDs in the request
        unique_ids = list(set(vector_ids))
        
        # Use a conservative batch size (e.g., 50) to prevent URL length limits (HTTP 414)
        BATCH_SIZE = 50
        
        for i in range(0, len(unique_ids), BATCH_SIZE):
            batch = unique_ids[i:i + BATCH_SIZE]
            try:
                resp = index.fetch(ids=batch, namespace=self.namespace)
                if hasattr(resp, "vectors") and resp.vectors:
                    results.update(resp.vectors)
                elif isinstance(resp, dict) and "vectors" in resp:
                    results.update(resp["vectors"])
            except Exception as e:
                logger.error(f"Pinecone fetch error for batch {i}-{i+len(batch)}: {str(e)}")
                # We continue fetching other batches even if one fails
        return results

    async def resolve_parent_chunks(self, matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Takes a list of search results (matches) and if any are 'child' chunks,
        fetches their 'parent_chunk_id' from Pinecone and returns a deduplicated list
        of parent contexts for LLM generation.
        """
        parent_ids_to_fetch = set()
        resolved_results = []
        
        for match in matches:
            meta = match.get("metadata", {})
            chunk_type = meta.get("chunk_type", "paragraph")
            parent_id = meta.get("parent_chunk_id")
            
            if chunk_type == "child" and parent_id:
                # Need to resolve this parent
                parent_ids_to_fetch.add(parent_id)
            else:
                # It's already a parent or standard chunk, keep it
                resolved_results.append(match)
                
        if parent_ids_to_fetch:
            parent_vectors = await self.fetch_vectors(list(parent_ids_to_fetch))
            for p_id, p_data in parent_vectors.items():
                meta = getattr(p_data, "metadata", None)
                if meta is None and hasattr(p_data, "get"):
                    meta = p_data.get("metadata", {})
                
                # Default score to 1.0 since it was explicitly resolved as parent context
                resolved_results.append({
                    "id": p_id,
                    "score": 1.0, 
                    "text": meta.get("text", ""),
                    "source": meta.get("source", ""),
                    "document_id": meta.get("document_id", ""),
                    "metadata": meta,
                })
                
        # Deduplicate by ID
        unique_results = []
        seen = set()
        for res in resolved_results:
            if res["id"] not in seen:
                seen.add(res["id"])
                unique_results.append(res)
                
        # Sort by score descending
        unique_results.sort(key=lambda x: x["score"], reverse=True)
        return unique_results
