from fastapi import APIRouter, Depends, Query
from typing import List, Dict, Any
from core.database import col_knowledge_bases, col_documents, col_companies
from bson import ObjectId

router = APIRouter(tags=["Admin - Knowledge"])

@router.get("/knowledge-bases", summary="List all knowledge bases platform-wide")
async def list_all_knowledge_bases(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
):
    """Admin endpoint to see all KBs across all companies."""
    kbs = await col_knowledge_bases().find().skip(skip).limit(limit).to_list(length=limit)
    
    # Fetch company names for context
    company_ids = list(set([kb["company_id"] for kb in kbs]))
    
    # Fix: convert string company_ids to ObjectIds
    object_ids = []
    for cid in company_ids:
        if ObjectId.is_valid(cid):
            object_ids.append(ObjectId(cid))
            
    companies = await col_companies().find({"_id": {"$in": object_ids}}).to_list(length=len(object_ids))
    company_map = {str(c["_id"]): c["name"] for c in companies}
    
    formatted = []
    for kb in kbs:
        kb_id_str = str(kb["_id"])
        formatted.append({
            "id": kb_id_str,
            "company_id": kb["company_id"],
            "company_name": company_map.get(kb["company_id"], "Unknown"),
            "name": kb["name"],
            "total_documents": kb.get("total_documents", 0),
            "total_chunks": kb.get("total_chunks", 0),
            "created_at": kb.get("created_at"),
        })
    return {"knowledge_bases": formatted, "count": len(formatted)}


@router.get("/documents", summary="List all documents platform-wide")
async def list_all_documents(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, le=100),
):
    """Admin endpoint to see all document metadata across all companies."""
    docs = await col_documents().find().sort("created_at", -1).skip(skip).limit(limit).to_list(length=limit)
    
    # Fetch company names
    company_ids = list(set([doc["company_id"] for doc in docs]))
    
    # Fix: convert string company_ids to ObjectIds
    object_ids = []
    for cid in company_ids:
        if ObjectId.is_valid(cid):
            object_ids.append(ObjectId(cid))
            
    companies = await col_companies().find({"_id": {"$in": object_ids}}).to_list(length=len(object_ids))
    company_map = {str(c["_id"]): c["name"] for c in companies}
    
    formatted = []
    for doc in docs:
        doc_id_str = str(doc["_id"])
        formatted.append({
            "id": doc_id_str,
            "company_id": doc["company_id"],
            "company_name": company_map.get(doc["company_id"], "Unknown"),
            "knowledge_base_id": doc["knowledge_base_id"],
            "filename": doc["filename"],
            "status": doc.get("status", "unknown"),
            "file_size_bytes": doc.get("file_size_bytes", 0),
            "chunk_count": doc.get("chunk_count", 0),
            "created_at": doc.get("created_at"),
        })
    return {"documents": formatted, "count": len(formatted)}


@router.get("/documents/{doc_id}/chunks", summary="Get document chunks platform-wide")
async def get_document_chunks(doc_id: str):
    doc = await col_documents().find_one({"_id": ObjectId(doc_id)})
    if not doc:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Document not found")
        
    from services.knowledge_service import get_document_chunks
    chunks = await get_document_chunks(doc["company_id"], doc["knowledge_base_id"], doc_id)
    
    return {"chunks": chunks, "count": len(chunks)}
