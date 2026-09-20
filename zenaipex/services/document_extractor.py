"""
Zenaipex AI — Document Extractor Service.

Provides reusable modular functions to extract text from different file formats.
"""
import logging
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

class NeedsOCRError(Exception):
    """Exception raised when a document is scanned/image-only and requires OCR."""
    pass

def normalize_extracted_text(text: str) -> str:
    """
    Clean and normalize extracted text.
    Preserves all single newlines so semantic chunker can parse line-by-line.
    """
    import re
    # Remove trailing/leading whitespaces on each line but keep the line breaks
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    # Replace 3 or more consecutive newlines with exactly 2 newlines (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def extract_txt_text(file_path: str) -> Optional[str]:
    """Extract text from a plain TXT or Markdown file."""
    try:
        with open(file_path, "rb") as f:
            content_bytes = f.read()
        try:
            return normalize_extracted_text(content_bytes.decode("utf-8"))
        except UnicodeDecodeError:
            return normalize_extracted_text(content_bytes.decode("latin-1"))
    except Exception as e:
        logger.error(f"Failed to extract TXT text from {file_path}: {e}")
        return None

def extract_pdf_text(file_path: str) -> Optional[str]:
    """Extract readable text from a PDF file using PyPDF2."""
    try:
        from PyPDF2 import PdfReader
        from PyPDF2.errors import PdfReadError
        
        text_parts = []
        with open(file_path, "rb") as f:
            try:
                reader = PdfReader(f)
            except Exception as e:
                raise ValueError("PDF file is corrupted or malformed.")
            
            if reader.is_encrypted:
                raise ValueError("PDF is password protected and cannot be read.")
                
            if len(reader.pages) == 0:
                raise ValueError("PDF is empty (0 pages).")
                
            for i, page in enumerate(reader.pages):
                text_parts.append(f"\n\n---PAGE {i+1}---\n\n")
                text_parts.append(page.extract_text() or "")
                
        final_text = "\n\n".join(text_parts).strip()
        final_text = normalize_extracted_text(final_text)
        
        if not final_text or len(final_text) < 50:
            raise NeedsOCRError("Could not extract sufficient selectable text from this PDF. OCR is required for image-only/scanned PDFs.")
            
        return final_text
    except ImportError:
        logger.error("PyPDF2 is not installed.")
        raise ValueError("Server configuration error: PDF extraction library missing.")
    except (ValueError, NeedsOCRError):
        raise
    except Exception as e:
        logger.error(f"Failed to extract PDF text from {file_path}: {e}")
        raise ValueError(f"PDF text could not be read: {str(e)}")

def extract_docx_text(file_path: str) -> Optional[str]:
    """Extract paragraphs from a DOCX file using python-docx."""
    try:
        import docx
        doc = docx.Document(file_path)
        text_parts = [para.text for para in doc.paragraphs if para.text.strip()]
        text = "\n\n".join(text_parts).strip()
        return normalize_extracted_text(text)
    except ImportError:
        logger.error("python-docx is not installed.")
        return None
    except Exception as e:
        logger.error(f"Failed to extract DOCX text from {file_path}: {e}")
        return None

def extract_text(file_path: str, filename: str, content_type: str = "") -> str:
    """
    Route extraction to the appropriate handler based on filename or MIME type.
    Returns the extracted text or raises ValueError if unsupported or extraction fails.
    """
    filename_lower = filename.lower()
    content_type_lower = content_type.lower()
    
    text = None
    
    if filename_lower.endswith(".pdf") or "pdf" in content_type_lower:
        text = extract_pdf_text(file_path)
    elif filename_lower.endswith(".docx") or "officedocument.wordprocessingml" in content_type_lower:
        text = extract_docx_text(file_path)
    elif filename_lower.endswith(".txt") or filename_lower.endswith(".md") or "text/plain" in content_type_lower:
        text = extract_txt_text(file_path)
    else:
        # Fallback for unknown files, attempt reading as TXT
        text = extract_txt_text(file_path)
        
    if not text:
        raise ValueError(f"Could not extract text from {filename}. File may be empty, unsupported, or corrupted.")
        
    return text
