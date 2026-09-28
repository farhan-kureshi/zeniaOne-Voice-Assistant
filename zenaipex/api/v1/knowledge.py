"""
Zenaipex AI — Knowledge Base API router.

GET    /api/v1/companies/{id}/knowledge-bases         List KBs
POST   /api/v1/companies/{id}/knowledge-bases         Create KB
GET    /api/v1/companies/{id}/knowledge-bases/{kb}    Get KB details + stats
DELETE /api/v1/companies/{id}/knowledge-bases/{kb}    Delete KB + all vectors

POST   /api/v1/companies/{id}/knowledge-bases/{kb}/documents       Upload document
GET    /api/v1/companies/{id}/knowledge-bases/{kb}/documents       List documents
DELETE /api/v1/companies/{id}/knowledge-bases/{kb}/documents/{doc} Delete document
POST   /api/v1/companies/{id}/knowledge-bases/{kb}/search          Search knowledge base
"""
from fastapi import APIRouter, Depends, Path, Query, UploadFile, File, Form
from pydantic import BaseModel
from typing import Optional
from bson import ObjectId
from datetime import datetime, timezone

from core.dependencies import get_auth_context, get_unverified_auth_context, require_admin, require_onboarding_admin, AuthContext
from core.exceptions import NotFoundError
from core.database import col_knowledge_bases, col_documents
from models.knowledge_base import KnowledgeBaseCreate
from services import knowledge_service
from services.storage_service import save_upload

router = APIRouter(tags=["Knowledge Base"])


def _fmt_kb(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "company_id": doc["company_id"],
        "name": doc["name"],
        "description": doc.get("description"),
        "pinecone_namespace": doc.get("pinecone_namespace"),
        "embedding_model": doc.get("embedding_model"),
        "total_documents": doc.get("total_documents", 0),
        "total_chunks": doc.get("total_chunks", 0),
        "total_vectors": doc.get("total_vectors", 0),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
    }


def _fmt_doc(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "knowledge_base_id": doc["knowledge_base_id"],
        "filename": doc["filename"],
        "content_type": doc.get("content_type", "text/plain"),
        "file_size_bytes": doc.get("file_size_bytes", 0),
        "status": doc.get("status", "pending"),
        "chunk_count": doc.get("chunk_count", 0),
        "error_message": doc.get("error_message"),
        "created_at": doc.get("created_at"),
        "updated_at": doc.get("updated_at"),
        "source_url": doc.get("source_url"),
        "auto_sync": doc.get("auto_sync", False)
    }


# ── Knowledge Base endpoints ──────────────────────────────────────────────────

@router.get("/companies/{company_id}/knowledge-bases", summary="List knowledge bases")
async def list_kbs(
    company_id: str = Path(...),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    kbs = await knowledge_service.list_knowledge_bases(company_id)
    return {"knowledge_bases": [_fmt_kb(k) for k in kbs]}


@router.post(
    "/companies/{company_id}/knowledge-bases",
    status_code=201,
    summary="Create knowledge base",
)
async def create_kb(
    body: KnowledgeBaseCreate,
    company_id: str = Path(...),
    ctx: AuthContext = Depends(require_onboarding_admin),
):
    """
    Create a new knowledge base. Admins only.
    A Pinecone namespace (= company_id) is automatically assigned.
    """
    kb = await knowledge_service.create_knowledge_base(
        company_id=company_id,
        name=body.name,
        description=body.description,
        embedding_model=body.embedding_model,
    )
    return _fmt_kb(kb)


@router.get(
    "/companies/{company_id}/knowledge-bases/{kb_id}",
    summary="Get knowledge base details",
)
async def get_kb(
    company_id: str = Path(...),
    kb_id: str = Path(...),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    kb = await knowledge_service.get_knowledge_base(company_id, kb_id)
    if not kb:
        raise NotFoundError("Knowledge base")
    return _fmt_kb(kb)


@router.delete(
    "/companies/{company_id}/knowledge-bases/{kb_id}",
    summary="Delete knowledge base and all its vectors",
)
async def delete_kb(
    company_id: str = Path(...),
    kb_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin),
):
    """Delete KB record and all its documents/vectors. Irreversible. Admin only."""
    kb = await knowledge_service.get_knowledge_base(company_id, kb_id)
    if not kb:
        raise NotFoundError("Knowledge base")

    # Delete all documents first (handles Pinecone vector cleanup)
    docs = await col_documents().find({"company_id": company_id, "knowledge_base_id": kb_id}).to_list(length=10000)
    for doc in docs:
        try:
            await knowledge_service.delete_document(company_id, str(doc["_id"]))
        except Exception:
            pass

    # Delete KB record
    await col_knowledge_bases().delete_one({"_id": ObjectId(kb_id)})
    return {"success": True, "deleted_documents": len(docs)}


# ── Document endpoints ────────────────────────────────────────────────────────

@router.post(
    "/companies/{company_id}/knowledge-bases/{kb_id}/documents",
    status_code=201,
    summary="Upload and index a document",
)
async def upload_document(
    company_id: str = Path(...),
    kb_id: str = Path(...),
    file: UploadFile = File(...),
    ctx: AuthContext = Depends(require_onboarding_admin),
):
    """
    Upload a text/pdf/docx file and index it into the company's knowledge base.
    """
    # Read content
    content_bytes = await file.read()
    
    # 1. File size validation (Max 50MB)
    if len(content_bytes) > 50 * 1024 * 1024:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="File too large. Maximum size is 50MB.")
        
    if len(content_bytes) == 0:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="File is empty.")

    # 2. Content type and magic bytes validation
    filename = file.filename or "document.txt"
    content_type = file.content_type or "text/plain"
    
    filename_lower = filename.lower()
    if filename_lower.endswith(".pdf"):
        if not content_bytes.startswith(b"%PDF"):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invalid PDF file format.")
    elif filename_lower.endswith(".docx"):
        if not content_bytes.startswith(b"PK\x03\x04"):
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail="Invalid DOCX file format.")
    
    allowed_types = [
        "application/pdf", 
        "text/plain", 
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]
    if content_type not in allowed_types:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Unsupported file type. Allowed: PDF, TXT, DOCX.")

    # 3. Deduplication and Replacement check
    existing_docs = await col_documents().find({
        "company_id": company_id,
        "knowledge_base_id": kb_id,
        "filename": filename
    }).to_list(length=10)
    
    target_existing_doc = None
    for existing_doc in existing_docs:
        if existing_doc.get("file_size_bytes") == len(content_bytes) and existing_doc.get("status") in ["ready", "processing"]:
            # Exact match, deduplicate
            await col_documents().update_one({"_id": existing_doc["_id"]}, {"$set": {"updated_at": datetime.now(timezone.utc)}})
            existing_doc["updated_at"] = datetime.now(timezone.utc)
            return _fmt_doc(existing_doc)
        else:
            # Phase 8: Safe Versioned Replacement
            # We do NOT delete the old vectors here. We pass the old doc to ingest_document 
            # to increment the version and safely replace vectors only upon success.
            target_existing_doc = existing_doc
            break

    # Save to storage
    storage_path = await save_upload(company_id, filename, content_bytes)

    doc = await knowledge_service.ingest_document(
        company_id=company_id,
        kb_id=kb_id,
        filename=filename,
        content_type=content_type,
        storage_path=storage_path,
        file_size_bytes=len(content_bytes),
        existing_doc=target_existing_doc
    )
    return _fmt_doc(doc)

class UrlUploadRequest(BaseModel):
    url: str

@router.post(
    "/companies/{company_id}/knowledge-bases/{kb_id}/url",
    status_code=201,
    summary="Scrape and index a website URL",
)
async def upload_url(
    req: UrlUploadRequest,
    company_id: str = Path(...),
    kb_id: str = Path(...),
    ctx: AuthContext = Depends(require_onboarding_admin),
):
    """
    Scrape text from a URL and index it into the knowledge base.
    """
    from services.document_extractor import extract_url_text
    from fastapi import HTTPException
    
    url = req.url.strip()
    if not url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL. Must start with http:// or https://")
        
    # Fetch content (this blocks briefly, but requests has a 15s timeout)
    try:
        text_content = await extract_url_text(url)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    content_bytes = text_content.encode("utf-8")
    
    # Create a safe filename from URL
    import re
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', url.split("://")[-1])[:50]
    filename = f"{safe_name}.txt"
    content_type = "text/plain"
    
    # Deduplication
    existing_docs = await col_documents().find({
        "company_id": company_id,
        "knowledge_base_id": kb_id,
        "filename": filename
    }).to_list(length=10)
    
    target_existing_doc = None
    for existing_doc in existing_docs:
        if existing_doc.get("status") in ["ready", "processing"]:
            target_existing_doc = existing_doc
            break
            
    storage_path = await save_upload(company_id, filename, content_bytes)
    
    doc = await knowledge_service.ingest_document(
        company_id=company_id,
        kb_id=kb_id,
        filename=filename,
        content_type=content_type,
        storage_path=storage_path,
        file_size_bytes=len(content_bytes),
        existing_doc=target_existing_doc
    )
    
    # Tag URL for daily automated re-sync
    await col_documents().update_one(
        {"_id": doc["_id"]},
        {"$set": {"source_url": url, "auto_sync": True}}
    )
    doc["source_url"] = url
    doc["auto_sync"] = True
    
    return _fmt_doc(doc)


class TextUploadRequest(BaseModel):
    title: str
    content: str

@router.post(
    "/companies/{company_id}/knowledge-bases/{kb_id}/text",
    status_code=201,
    summary="Index raw text as a document",
)
async def upload_text(
    req: TextUploadRequest,
    company_id: str = Path(...),
    kb_id: str = Path(...),
    ctx: AuthContext = Depends(require_onboarding_admin),
):
    """
    Take raw text, save it as a .txt file, and index it into the knowledge base.
    """
    from fastapi import HTTPException
    import re
    
    if not req.title.strip() or not req.content.strip():
        raise HTTPException(status_code=400, detail="Title and content are required.")
        
    content_bytes = req.content.encode("utf-8")
    
    # Create a safe filename from the title
    safe_name = re.sub(r'[^a-zA-Z0-9]', '_', req.title.strip())[:50]
    filename = f"{safe_name}.txt"
    content_type = "text/plain"
    
    # Deduplication
    existing_docs = await col_documents().find({
        "company_id": company_id,
        "knowledge_base_id": kb_id,
        "filename": filename
    }).to_list(length=10)
    
    target_existing_doc = None
    for existing_doc in existing_docs:
        if existing_doc.get("status") in ["ready", "processing"]:
            target_existing_doc = existing_doc
            break
            
    storage_path = await save_upload(company_id, filename, content_bytes)
    
    doc = await knowledge_service.ingest_document(
        company_id=company_id,
        kb_id=kb_id,
        filename=filename,
        content_type=content_type,
        storage_path=storage_path,
        file_size_bytes=len(content_bytes),
        existing_doc=target_existing_doc
    )
    return _fmt_doc(doc)


@router.post(
    "/companies/{company_id}/knowledge-bases/{kb_id}/documents/{doc_id}/retry",
    summary="Retry processing a document",
)
async def retry_document(
    company_id: str = Path(...),
    kb_id: str = Path(...),
    doc_id: str = Path(...),
    ctx: AuthContext = Depends(require_onboarding_admin),
):
    """Retry failed document processing."""
    doc = await knowledge_service.reprocess_document(company_id, doc_id)
    return _fmt_doc(doc)


@router.get(
    "/companies/{company_id}/knowledge-bases/{kb_id}/documents",
    summary="List documents",
)
async def list_documents(
    company_id: str = Path(...),
    kb_id: str = Path(...),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, le=100),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    docs = await knowledge_service.list_documents(company_id, kb_id, skip, limit)
    return {"documents": [_fmt_doc(d) for d in docs], "count": len(docs)}


@router.delete(
    "/companies/{company_id}/knowledge-bases/{kb_id}/documents/{doc_id}",
    summary="Delete document and its vectors",
)
async def delete_document(
    company_id: str = Path(...),
    kb_id: str = Path(...),
    doc_id: str = Path(...),
    ctx: AuthContext = Depends(require_admin),
):
    """Delete a document and remove its Pinecone vectors. Admin only."""
    await knowledge_service.delete_document(company_id, doc_id)
    return {"success": True, "deleted": doc_id}


@router.get(
    "/companies/{company_id}/knowledge-bases/{kb_id}/documents/{doc_id}/chunks",
    summary="Get document chunks",
)
async def get_document_chunks(
    company_id: str = Path(...),
    kb_id: str = Path(...),
    doc_id: str = Path(...),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """Get all chunks for a specific document directly from Pinecone."""
    chunks = await knowledge_service.get_document_chunks(company_id, kb_id, doc_id)
    return {"chunks": chunks}


@router.get(
    "/companies/{company_id}/knowledge-bases/{kb_id}/documents/{doc_id}/download",
    summary="Download or view a document",
)
async def download_document(
    company_id: str = Path(...),
    kb_id: str = Path(...),
    doc_id: str = Path(...),
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """Secure endpoint to download or preview a document file."""
    doc = await knowledge_service.get_document(company_id, doc_id)
    if not doc:
        raise NotFoundError("Document")
        
    storage_path = doc.get("storage_path")
    if not storage_path:
        raise NotFoundError("Document file not found in storage")
        
    import os
    from fastapi.responses import FileResponse
    if not os.path.exists(storage_path):
        raise NotFoundError("Document file not found on disk")
        
    return FileResponse(
        path=storage_path,
        filename=doc.get("filename", "document"),
        media_type=doc.get("content_type", "application/octet-stream")
    )



@router.post(
    "/companies/{company_id}/knowledge-bases/{kb_id}/search",
    summary="Search knowledge base",
)
async def search_kb(
    company_id: str = Path(...),
    kb_id: str = Path(...),
    query: str = "",
    top_k: int = 3,
    ctx: AuthContext = Depends(get_unverified_auth_context),
):
    """
    Search the company's knowledge base with a natural language query.
    Results are scoped strictly to this company's namespace.
    """
    kb = await knowledge_service.get_knowledge_base(company_id, kb_id)
    if not kb:
        raise NotFoundError("Knowledge base")

    from ai.vector_store import NamespacedVectorStore
    vs = NamespacedVectorStore(namespace=kb["pinecone_namespace"])
    results = vs.similarity_search(query, top_k=top_k)
    return {"query": query, "results": results, "namespace": kb["pinecone_namespace"]}
