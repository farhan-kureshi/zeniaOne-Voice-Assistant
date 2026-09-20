"""
Zenaipex AI — KnowledgeBase and Document models.

A KnowledgeBase is a per-company vector store namespace in Pinecone.
Documents are the source files uploaded by the company and chunked
into Pinecone vectors under the company's namespace.
"""
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


# ── Knowledge Base ────────────────────────────────────────────────────────────

class KnowledgeBaseCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="HuggingFace model used for embedding documents"
    )


class KnowledgeBaseUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class KnowledgeBase(BaseModel):
    """KnowledgeBase document as stored in MongoDB."""
    id: str
    company_id: str
    name: str
    description: Optional[str] = None

    # Pinecone isolation: namespace = company_id (one KB per company for now;
    # later can expand to multiple KBs per company with sub-namespaces)
    pinecone_namespace: str  # = company_id

    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # Aggregate stats (updated when documents are processed)
    total_documents: int = 0
    total_chunks: int = 0
    total_vectors: int = 0

    created_at: datetime
    updated_at: datetime


class KnowledgeBaseResponse(BaseModel):
    id: str
    company_id: str
    name: str
    description: Optional[str] = None
    pinecone_namespace: str
    embedding_model: str
    total_documents: int
    total_chunks: int
    total_vectors: int
    created_at: datetime
    updated_at: datetime


# ── Document ──────────────────────────────────────────────────────────────────

class DocumentStatus(str, Enum):
    PENDING = "pending"         # Uploaded, not yet processed
    PROCESSING = "processing"   # Chunking + embedding in progress
    READY = "ready"             # Indexed in Pinecone, ready for RAG
    FAILED = "failed"           # Processing error


class DocumentCreate(BaseModel):
    """Metadata for a newly uploaded document."""
    filename: str
    content_type: str = "text/plain"
    # Raw text content (for txt/md files uploaded directly)
    content: Optional[str] = None


class Document(BaseModel):
    """Document record in MongoDB."""
    id: str
    company_id: str
    knowledge_base_id: str
    filename: str
    content_type: str = "text/plain"
    file_size_bytes: int = 0

    # Content fingerprint to prevent re-indexing unchanged docs
    content_hash: str = ""
    storage_path: Optional[str] = None

    # Processing results
    status: DocumentStatus = DocumentStatus.PENDING
    chunk_count: int = 0
    vector_ids: List[str] = Field(default_factory=list)
    error_message: Optional[str] = None

    created_at: datetime
    updated_at: datetime

    class Config:
        use_enum_values = True


class DocumentResponse(BaseModel):
    id: str
    knowledge_base_id: str
    filename: str
    file_size_bytes: int
    status: str
    chunk_count: int
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime
