"""
Zenaipex AI — Knowledge base service.

Handles document upload, chunking, embedding, and Pinecone upsert.
Each company's vectors are isolated in their own Pinecone namespace (= company_id).
"""
import hashlib
import logging
import time
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from bson import ObjectId

from core.database import col_knowledge_bases, col_documents, col_activity_logs
from core.config import settings
from core.exceptions import NotFoundError, PlanLimitExceededError
from services.tenant_service import enforce_plan_limit, get_subscription
from ai.vector_store import NamespacedVectorStore
from services.document_extractor import extract_text
from services.storage_service import delete_file
import asyncio

logger = logging.getLogger(__name__)


# ── Knowledge Base CRUD ───────────────────────────────────────────────────────

async def create_knowledge_base(
    company_id: str,
    name: str,
    description: Optional[str] = None,
    embedding_model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a new knowledge base for a company.

    NOTE: In Phase 2, each company gets ONE knowledge base (namespace = company_id).
    Future phases can allow multiple KBs with sub-namespaces.
    """
    # For now: namespace = company_id (simple, secure)
    pinecone_namespace = company_id

    now = datetime.now(timezone.utc)
    kb_doc = {
        "company_id": company_id,
        "name": name,
        "description": description,
        "pinecone_namespace": pinecone_namespace,
        "embedding_model": embedding_model or settings.embedding_model,
        "embedding_dimension": settings.embedding_dimension,
        "total_documents": 0,
        "total_chunks": 0,
        "total_vectors": 0,
        "created_at": now,
        "updated_at": now,
    }
    result = await col_knowledge_bases().insert_one(kb_doc)
    kb_doc["_id"] = result.inserted_id
    logger.info(f"Knowledge base created: {name} for company {company_id}")
    return kb_doc


async def get_knowledge_base(company_id: str, kb_id: str) -> Optional[Dict[str, Any]]:
    """Fetch knowledge base by ID, scoped to company."""
    try:
        return await col_knowledge_bases().find_one({
            "_id": ObjectId(kb_id),
            "company_id": company_id,
        })
    except Exception:
        return None


async def list_knowledge_bases(company_id: str) -> List[Dict[str, Any]]:
    """List all knowledge bases for a company."""
    return await col_knowledge_bases().find({"company_id": company_id}).to_list(length=50)


async def get_or_create_default_kb(company_id: str, company_name: str) -> Dict[str, Any]:
    """
    Get the company's default knowledge base, creating one if it doesn't exist.
    Used during company onboarding and migration.
    """
    existing = await col_knowledge_bases().find_one({"company_id": company_id})
    if existing:
        return existing
    return await create_knowledge_base(
        company_id=company_id,
        name=f"{company_name} Knowledge Base",
        description="Default knowledge base",
    )


# ── Document Management ───────────────────────────────────────────────────────

# We have migrated chunking logic to ai.semantic_chunker.SemanticChunker

def _content_hash(content: str) -> str:
    """SHA-256 hash of document content for dedup checking."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

async def ingest_document(
    company_id: str,
    kb_id: str,
    filename: str,
    content_type: str,
    storage_path: str,
    file_size_bytes: int,
    existing_doc: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Start document ingestion pipeline. Creates document record and kicks off background processing.
    """
    await enforce_plan_limit(company_id, "max_kb_docs")

    kb = await get_knowledge_base(company_id, kb_id)
    if not kb:
        raise NotFoundError("Knowledge base")

    now = datetime.now(timezone.utc)
    
    if existing_doc:
        doc_id = str(existing_doc["_id"])
        target_version = existing_doc.get("version", 1) + 1
        
        # Update existing record to processing state
        await col_documents().update_one(
            {"_id": existing_doc["_id"]},
            {"$set": {
                "status": "processing",
                "file_size_bytes": file_size_bytes,
                "storage_path": storage_path,
                "error_message": None,
                "updated_at": now
            }}
        )
        doc_record = existing_doc
        doc_record["version"] = target_version
    else:
        target_version = 1
        doc_record = {
            "company_id": company_id,
            "knowledge_base_id": kb_id,
            "filename": filename,
            "content_type": content_type,
            "file_size_bytes": file_size_bytes,
            "storage_path": storage_path,
            "content_hash": "",
            "status": "processing",
            "chunk_count": 0,
            "vector_ids": [],
            "version": target_version,
            "error_message": None,
            "created_at": now,
            "updated_at": now,
        }
        doc_result = await col_documents().insert_one(doc_record)
        doc_id = str(doc_result.inserted_id)
        doc_record["_id"] = doc_result.inserted_id

    # Kick off background task with target version
    asyncio.create_task(_process_document_task(company_id, kb_id, doc_id, storage_path, filename, content_type, target_version))

    await col_activity_logs().insert_one({
        "actor_name": "System",
        "actor_email": "system@zenaipex.com",
        "action": "document_uploaded",
        "target": filename,
        "details": f"Document uploaded to knowledge base {kb_id}",
        "created_at": datetime.now(timezone.utc)
    })

    return doc_record


async def _process_document_task(company_id: str, kb_id: str, doc_id: str, storage_path: str, filename: str, content_type: str, target_version: int = 1):
    """Background task for extracting, chunking, embedding, and upserting safely."""
    try:
        kb = await get_knowledge_base(company_id, kb_id)
        if not kb:
            raise NotFoundError("Knowledge base")
        namespace = kb["pinecone_namespace"]

        # Extract text
        content = extract_text(storage_path, filename, content_type)
        content_hash = _content_hash(content)

        # Initialize namespaced vector store
        vs = NamespacedVectorStore(namespace=namespace)

        # Semantic chunk content
        from ai.semantic_chunker import SemanticChunker
        from ai.chunk_validator import CoverageValidator
        
        chunker = SemanticChunker(max_chunk_size=1500)
        chunk_dicts = chunker.chunk(content)
        chunks = [c["text"] for c in chunk_dicts]
        
        # Validation Pass
        validator = CoverageValidator(content, chunk_dicts)
        val_report = validator.validate()
        
        telemetry = val_report.get("telemetry", {})
        
        # Dump uncovered report for debugging
        uncovered_meaningful = [u for u in val_report.get("uncovered_report", []) if not u.get("filtered_as_pdf_noise")]
        if uncovered_meaningful:
            logger.warning(f"\n--- ⚠️ UNCOVERED CONTENT REPORT ({len(uncovered_meaningful)} items) ---")
            for u in uncovered_meaningful[:50]: # limit to 50 for logs
                logger.warning(f"Pg {u['page_number']} | Idx {u['source_unit_index']} | {u['reason']}: {u['source_text_preview']}")
            if len(uncovered_meaningful) > 50:
                logger.warning(f"... and {len(uncovered_meaningful) - 50} more missing items.")
            logger.warning("----------------------------------------\n")
            
        if not val_report["success"]:
            logger.error(f"❌ Chunk validation failed for {filename}. Aborting ingestion.")
            logger.error(f"Coverage: {val_report['coverage_percent']}% (Meaningful: {telemetry.get('MATCHED_SOURCE_CHARS')}/{telemetry.get('MEANINGFUL_SOURCE_CHARS')}), Violations: {val_report['cross_module_violations']}")
            raise ValueError(f"Document chunking failed coverage guarantees. Coverage: {val_report['coverage_percent']}%, Cross-module violations: {val_report['cross_module_violations']}")
        
        if chunks:
            avg_size = sum(len(c) for c in chunks) / len(chunks)
            min_size = min(len(c) for c in chunks)
            max_size = max(len(c) for c in chunks)
            
            # Module counts
            modules = {}
            for c in chunk_dicts:
                m = c["metadata"].get("module_number", "") + " " + c["metadata"].get("module_name", "")
                modules[m.strip()] = modules.get(m.strip(), 0) + 1
                
            logger.info(f"--- CHUNKING TELEMETRY ---")
            logger.info(f"Document: {filename}")
            logger.info(f"Total Chunks: {len(chunks)} | Parent Chunks: {len([c for c in chunk_dicts if c['metadata'].get('chunk_type') == 'parent'])}")
            
            for key, val in telemetry.items():
                logger.info(f"{key}: {val}")
            
            logger.info(f"First 10 Chunks Preview:")
            for i, c in enumerate(chunk_dicts[:10]):
                preview = c["text"][:80].replace("\n", " ") + "..."
                meta = c["metadata"]
                logger.info(f"  [{i+1}] {meta.get('chunk_type', 'paragraph')} | Pg {meta.get('page_start')} | {meta.get('module_number')} {meta.get('module_name')} -> {meta.get('section')} | {preview}")
            logger.info(f"--------------------------")
        else:
            logger.info(f"Document '{filename}': 0 chunks extracted")

        # Generate embeddings
        embeddings = vs.generate_embeddings(chunks)
        
        if len(chunks) != len(embeddings):
            raise ValueError(f"Consistency error: {len(chunks)} chunks but {len(embeddings)} embeddings generated.")

        # Build vectors for Pinecone upsert
        vectors = []
        vector_ids = []
        for i, (chunk_dict, embedding) in enumerate(zip(chunk_dicts, embeddings)):
            chunk_text = chunk_dict["text"]
            chunk_meta = chunk_dict["metadata"]
            
            chunk_hash = hashlib.md5(chunk_text.encode("utf-8")).hexdigest()
            # Phase 8: Version-isolated Vector IDs
            vector_id = f"{company_id}_{doc_id}_v{target_version}_{i}_{chunk_hash[:8]}"
            vector_ids.append(vector_id)
            
            vectors.append({
                "id": vector_id,
                "values": embedding,
                "metadata": {
                    "text": chunk_text,
                    "source": filename,
                    "document_id": doc_id,
                    "company_id": company_id,
                    "chunk_index": i,
                    "chunk_id": vector_id,
                    "section": chunk_meta.get("section", "General"),
                    "subsection": chunk_meta.get("subsection", ""),
                    "content_type": chunk_meta.get("content_type", "paragraph"),
                    "chunk_type": chunk_meta.get("chunk_type", "paragraph"),
                    "page_start": chunk_meta.get("page_start", 1),
                    "page_end": chunk_meta.get("page_end", 1),
                    "parent_section": chunk_meta.get("parent_section", "General"),
                    "source_type": content_type,
                    "document_version": target_version,
                    "updated_at": datetime.now(timezone.utc).isoformat()
                },
            })
            
        if len(vectors) != len(chunks):
            raise ValueError(f"Consistency error: {len(vectors)} vectors built for {len(chunks)} chunks.")

        # Upsert to Pinecone
        logger.info(f"Upserting {len(vectors)} validated vectors to Pinecone namespace {namespace}...")
        start_time = time.time()
        await vs.upsert_vectors(vectors)
        indexing_duration = time.time() - start_time
        logger.info(f"✅ Upserted {len(vectors)} vectors in {indexing_duration:.2f}s")

        # Fetch old record to grab stale vector IDs
        old_doc = await col_documents().find_one({"_id": ObjectId(doc_id)})
        old_vector_ids = old_doc.get("vector_ids", []) if old_doc else []

        # Update document record FIRST so new vectors become active
        await col_documents().update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {
                "status": "ready",
                "version": target_version,
                "content_hash": content_hash,
                "extracted_text": content,
                "chunk_count": len(chunks),
                "vector_ids": vector_ids,
                "error_message": None,
                "updated_at": datetime.now(timezone.utc),
            }}
        )
        
        # Safe Replacement Cleanup: Deactivate/delete stale vectors ONLY AFTER new vectors succeed
        if old_vector_ids and target_version > 1:
            logger.info(f"Safe cleanup: Deleting {len(old_vector_ids)} stale vectors from previous version.")
            await vs.delete_vectors(old_vector_ids)

        # Update KB aggregate counts (delta)
        chunk_diff = len(chunks) - (old_doc.get("chunk_count", 0) if old_doc else 0)
        vector_diff = len(vectors) - (len(old_vector_ids) if old_doc else 0)
        doc_diff = 1 if target_version == 1 else 0
        
        await col_knowledge_bases().update_one(
            {"_id": ObjectId(kb_id)},
            {
                "$inc": {
                    "total_documents": doc_diff,
                    "total_chunks": chunk_diff,
                    "total_vectors": vector_diff,
                },
                "$set": {"updated_at": datetime.now(timezone.utc)}
            }
        )

        await col_activity_logs().insert_one({
            "actor_name": "System",
            "actor_email": "system@zenaipex.com",
            "action": "document_processed",
            "target": filename,
            "details": f"Document successfully processed into {len(chunks)} chunks",
            "created_at": datetime.now(timezone.utc)
        })

        logger.info(f"✅ Document processed: {filename} ({len(chunks)} chunks) → namespace={namespace}")

    except Exception as exc:
        from services.document_extractor import NeedsOCRError
        if isinstance(exc, NeedsOCRError):
            logger.error(f"⚠️ Document requires OCR: {filename} → {exc}")
            await col_documents().update_one(
                {"_id": ObjectId(doc_id)},
                {"$set": {
                    "status": "needs_ocr",
                    "error_message": "Document is scanned or image-only and requires OCR.",
                    "updated_at": datetime.now(timezone.utc),
                }}
            )
        else:
            logger.error(f"❌ Document processing failed: {filename} → {exc}")
            await col_documents().update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {
                "status": "failed",
                "error_message": str(exc),
                "updated_at": datetime.now(timezone.utc),
            }}
        )
        # We do NOT delete the old active vectors if indexing fails, preserving working previous state.
        logger.error(f"Error processing document {doc_id}: {str(exc)}", exc_info=True)

async def get_document(company_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
    """Fetch document by ID, scoped to company."""
    try:
        return await col_documents().find_one({
            "_id": ObjectId(doc_id),
            "company_id": company_id,
        })
    except Exception:
        return None

async def get_document_chunks(company_id: str, kb_id: str, doc_id: str) -> List[Dict[str, Any]]:
    """Fetch all chunks for a specific document directly from Pinecone."""
    import time
    start_time = time.time()
    
    doc = await get_document(company_id, doc_id)
    if not doc:
        raise NotFoundError("Document not found")
        
    vector_ids = doc.get("vector_ids", [])
    if not vector_ids:
        logger.info(f"Telemetry: document_id={doc_id} requested_chunk_count=0 batch_size=0 batch_count=0 fetched_count=0 failed_count=0 latency=0.00s")
        return []
        
    vs = NamespacedVectorStore(namespace=company_id)
    vectors = await vs.fetch_vectors(vector_ids)
    
    chunks = []
    for vid, vdata in vectors.items():
        meta = getattr(vdata, "metadata", None)
        if meta is None and hasattr(vdata, "get"):
            meta = vdata.get("metadata", {})
        elif meta is None:
            meta = {}
            
        text = meta.get("text", "") if hasattr(meta, "get") else getattr(meta, "text", "")
        module_number = meta.get("module_number", "") if hasattr(meta, "get") else getattr(meta, "module_number", "")
        module_name = meta.get("module_name", "") if hasattr(meta, "get") else getattr(meta, "module_name", "")
        
        if text.startswith("[Module:") and not module_number:
            import re
            header_match = re.search(r"\[Module:\s*(\d{2})?\s*([^|]+?)\s*\|", text)
            if header_match:
                module_number = header_match.group(1) or ""
                module_name = header_match.group(2).strip() or ""

        chunks.append({
            "chunk_id": vid,
            "chunk_index": int(meta.get("chunk_index", 0) if hasattr(meta, "get") else getattr(meta, "chunk_index", 0)),
            "text": text,
            "section": meta.get("section", "") if hasattr(meta, "get") else getattr(meta, "section", ""),
            "module_number": module_number,
            "module_name": module_name,
            "role": meta.get("role", "") if hasattr(meta, "get") else getattr(meta, "role", ""),
            "chunk_type": meta.get("chunk_type", "") if hasattr(meta, "get") else getattr(meta, "chunk_type", ""),
            "parent_chunk_id": meta.get("parent_chunk_id", "") if hasattr(meta, "get") else getattr(meta, "parent_chunk_id", ""),
            "page_number": meta.get("page_start", "") if hasattr(meta, "get") else getattr(meta, "page_start", ""),
        })
        
    # Sort chunks by their original sequential order
    chunks.sort(key=lambda x: x["chunk_index"])
    
    latency = time.time() - start_time
    requested_chunk_count = len(vector_ids)
    fetched_count = len(chunks)
    failed_count = requested_chunk_count - fetched_count
    
    # In vector_store we hardcoded BATCH_SIZE=50
    batch_size = 50
    batch_count = (len(set(vector_ids)) + batch_size - 1) // batch_size if vector_ids else 0
    
    logger.info(f"Telemetry: document_id={doc_id} requested_chunk_count={requested_chunk_count} batch_size={batch_size} batch_count={batch_count} fetched_count={fetched_count} failed_count={failed_count} latency={latency:.2f}s")
    
    return chunks

async def reprocess_document(company_id: str, doc_id: str) -> Dict[str, Any]:
    """Retry processing a failed or existing document."""
    doc = await col_documents().find_one({"_id": ObjectId(doc_id), "company_id": company_id})
    if not doc:
        raise NotFoundError("Document")

    storage_path = doc.get("storage_path")
    if not storage_path:
        raise ValueError("Cannot reprocess: original file storage path missing")

    # If document has existing vectors, we should delete them first before reprocessing
    old_vector_ids = doc.get("vector_ids", [])
    if old_vector_ids:
        kb = await get_knowledge_base(company_id, doc["knowledge_base_id"])
        if kb:
            vs = NamespacedVectorStore(namespace=kb["pinecone_namespace"])
            try:
                await vs.delete_vectors(old_vector_ids)
            except Exception as e:
                logger.error(f"Failed to delete old vectors during reprocess: {e}")
            
            # Decrement old counts from KB
            chunk_count = doc.get("chunk_count", 0)
            await col_knowledge_bases().update_one(
                {"_id": ObjectId(doc["knowledge_base_id"])},
                {
                    "$inc": {
                        "total_chunks": -chunk_count,
                        "total_vectors": -len(old_vector_ids),
                    },
                }
            )

    # Set status back to processing
    await col_documents().update_one(
        {"_id": ObjectId(doc_id)},
        {"$set": {
            "status": "processing",
            "error_message": None,
            "chunk_count": 0,
            "vector_ids": [],
            "updated_at": datetime.now(timezone.utc)
        }}
    )
    
    # Phase 12: Invalidate Cache
    from ai.config import invalidate_document_cache
    invalidate_document_cache(doc_id)

    # Kick off background task
    asyncio.create_task(_process_document_task(
        company_id=company_id,
        kb_id=doc["knowledge_base_id"],
        doc_id=doc_id,
        storage_path=storage_path,
        filename=doc["filename"],
        content_type=doc.get("content_type", "text/plain")
    ))
    
    doc["status"] = "processing"
    return doc


async def delete_document(company_id: str, doc_id: str) -> bool:
    """
    Delete a document and its Pinecone vectors.
    """
    doc = await col_documents().find_one({
        "_id": ObjectId(doc_id),
        "company_id": company_id,
    })
    if not doc:
        raise NotFoundError("Document")

    # Delete from Pinecone
    vector_ids = doc.get("vector_ids", [])
    if vector_ids:
        kb = await get_knowledge_base(company_id, doc["knowledge_base_id"])
        if kb:
            vs = NamespacedVectorStore(namespace=kb["pinecone_namespace"])
            await vs.delete_vectors(vector_ids)
            
    # Phase 12: Invalidate Cache
    from ai.config import invalidate_document_cache
    invalidate_document_cache(doc_id)

    # Delete from MongoDB
    await col_documents().delete_one({"_id": ObjectId(doc_id)})
    
    # Delete from local storage
    storage_path = doc.get("storage_path")
    if storage_path:
        await delete_file(storage_path)

    # Update KB aggregate counts
    chunk_count = doc.get("chunk_count", 0)
    await col_knowledge_bases().update_one(
        {"_id": ObjectId(doc["knowledge_base_id"])},
        {
            "$inc": {
                "total_documents": -1,
                "total_chunks": -chunk_count,
                "total_vectors": -len(vector_ids),
            },
            "$set": {"updated_at": datetime.now(timezone.utc)}
        }
    )
    
    await col_activity_logs().insert_one({
        "actor_name": "System",
        "actor_email": "system@zenaipex.com",
        "action": "document_deleted",
        "target": doc.get("filename", "Unknown"),
        "details": f"Document deleted from knowledge base",
        "created_at": datetime.now(timezone.utc)
    })
    
    return True


async def list_documents(
    company_id: str,
    kb_id: str,
    skip: int = 0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """List documents for a knowledge base, scoped to company."""
    return await col_documents().find({
        "company_id": company_id,
        "knowledge_base_id": kb_id,
    }).skip(skip).limit(limit).to_list(length=limit)
