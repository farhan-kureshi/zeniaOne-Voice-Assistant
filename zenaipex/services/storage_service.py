"""
Zenaipex AI — Local Storage Service.

Provides a safe local storage strategy for uploaded documents.
Structured so object storage (e.g. S3) can be dropped in later.
"""
import os
import logging
import uuid
from typing import Optional
from core.config import settings

logger = logging.getLogger(__name__)

# Base directory for local storage. In a real app, this should be configurable.
STORAGE_ROOT = os.path.join(os.getcwd(), "data", "uploads")

async def save_upload(company_id: str, filename: str, content: bytes) -> str:
    """
    Save an uploaded file to local storage.
    
    Args:
        company_id: The tenant's company ID (used for isolation).
        filename: The original filename.
        content: The raw bytes of the file.
        
    Returns:
        The relative or absolute path to the stored file.
    """
    # Create isolated directory: data/uploads/{company_id}
    company_dir = os.path.join(STORAGE_ROOT, company_id)
    os.makedirs(company_dir, exist_ok=True)
    
    # Generate unique safe filename
    safe_filename = f"{uuid.uuid4().hex}_{os.path.basename(filename)}"
    file_path = os.path.join(company_dir, safe_filename)
    
    with open(file_path, "wb") as f:
        f.write(content)
        
    logger.info(f"Saved file {filename} to {file_path}")
    return file_path

async def delete_file(file_path: str) -> bool:
    """
    Delete a file from storage.
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Deleted file {file_path}")
            return True
        return False
    except Exception as e:
        logger.error(f"Failed to delete file {file_path}: {e}")
        return False
