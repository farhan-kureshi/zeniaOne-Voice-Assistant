"""
Zenaipex AI — Document Extractor Service.

Provides reusable modular functions to extract clean, normalized text
from PDFs, DOCX, Markdown, Text, and tabular files.
"""
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

class NeedsOCRError(Exception):
    """Exception raised when a document is scanned/image-only and requires OCR."""
    pass

def sanitize_characters(text: str) -> str:
    """
    Sanitize character encoding artifacts, smart quotes, and unprintable glyphs.
    Converts Windows-1252/Unicode artifacts to clean standard representations.
    """
    if not text:
        return ""
    
    # Replace unicode replacement character and common broken quote encodings
    text = text.replace('\ufffd', '"')
    
    # Normalize curly/smart quotes and apostrophes
    text = re.sub(r'[\u201c\u201d\u201e\u201f\x93\x94]', '"', text)
    text = re.sub(r'[\u2018\u2019\u201a\u201b\x91\x92]', "'", text)
    
    # Normalize dashes and hyphens
    text = re.sub(r'[\u2013\u2014\u2015\x96\x97]', '-', text)
    
    # Normalize bullet characters to standard dash bullet
    text = re.sub(r'[\u2022\u2023\u25e6\u2043\u2219]', '• ', text)
    
    # Normalize multiple whitespace within lines (preserve newlines)
    text = re.sub(r'[ \t\r\f\v]+', ' ', text)
    
    # Clean non-printable control characters except standard whitespace
    text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
    
    return text

def normalize_extracted_text(text: str) -> str:
    """
    Clean and normalize extracted text.
    Preserves all single newlines so semantic chunker can parse line-by-line.
    """
    text = sanitize_characters(text)
    
    # Remove trailing/leading whitespaces on each line but keep the line breaks
    lines = [line.strip() for line in text.split("\n")]
    text = "\n".join(lines)
    
    # Clean repetitive footers like 'Page X of Y' or standalone page numbers
    text = re.sub(r'(?i)\bpage\s+\d+\s+of\s+\d+\b', '', text)
    
    # Replace 3 or more consecutive newlines with exactly 2 newlines (paragraph break)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def extract_txt_text(file_path: str) -> Optional[str]:
    """Extract text from plain TXT, CSV, or Markdown file."""
    try:
        with open(file_path, "rb") as f:
            content_bytes = f.read()
        try:
            return normalize_extracted_text(content_bytes.decode("utf-8"))
        except UnicodeDecodeError:
            try:
                return normalize_extracted_text(content_bytes.decode("utf-8-sig"))
            except UnicodeDecodeError:
                return normalize_extracted_text(content_bytes.decode("latin-1", errors="replace"))
    except Exception as e:
        logger.error(f"Failed to extract text from {file_path}: {e}")
        return None

def extract_pdf_text(file_path: str) -> Optional[str]:
    """
    Extract readable text from a PDF file.
    Prefers PyMuPDF (fitz) for superior layout and character accuracy,
    falling back to PyPDF2 if PyMuPDF is unavailable.
    """
    # Attempt 1: PyMuPDF (fitz)
    try:
        import pymupdf  # type: ignore
        text_parts = []
        doc = pymupdf.open(file_path)
        if len(doc) == 0:
            raise ValueError("PDF is empty (0 pages).")
        
        for i, page in enumerate(doc):
            page_text = page.get_text("text") or ""
            text_parts.append(f"\n\n---PAGE {i+1}---\n\n")
            text_parts.append(page_text)
            
        doc.close()
        final_text = normalize_extracted_text("\n\n".join(text_parts))
        
        if final_text and len(final_text) >= 50:
            return final_text
    except ImportError:
        pass
    except Exception as mupdf_err:
        logger.warning(f"PyMuPDF extraction failed on {file_path}: {mupdf_err}. Falling back to PyPDF2.")

    # Attempt 2: PyPDF2 fallback
    try:
        from PyPDF2 import PdfReader
        text_parts = []
        with open(file_path, "rb") as f:
            reader = PdfReader(f)
            if reader.is_encrypted:
                raise ValueError("PDF is password protected and cannot be read.")
            if len(reader.pages) == 0:
                raise ValueError("PDF is empty (0 pages).")
            for i, page in enumerate(reader.pages):
                text_parts.append(f"\n\n---PAGE {i+1}---\n\n")
                text_parts.append(page.extract_text() or "")
                
        final_text = normalize_extracted_text("\n\n".join(text_parts))
        if not final_text or len(final_text) < 50:
            raise NeedsOCRError("Could not extract sufficient selectable text from this PDF. OCR is required for image-only/scanned PDFs.")
        return final_text
    except NeedsOCRError:
        raise
    except Exception as e:
        logger.error(f"Failed to extract PDF text from {file_path}: {e}")
        raise ValueError(f"PDF text could not be read: {str(e)}")

def extract_docx_text(file_path: str) -> Optional[str]:
    """Extract paragraphs and tables from a DOCX file using python-docx."""
    try:
        import docx
        doc = docx.Document(file_path)
        text_parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text.strip())
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    text_parts.append(row_text)
        return normalize_extracted_text("\n\n".join(text_parts))
    except ImportError:
        logger.error("python-docx is not installed.")
        return None
    except Exception as e:
        logger.error(f"Failed to extract DOCX text from {file_path}: {e}")
        return None

def extract_text(file_path: str, filename: str, content_type: str = "") -> str:
    """
    Route extraction to the appropriate handler based on filename or MIME type.
    Returns the clean extracted text or raises ValueError if extraction fails.
    """
    filename_lower = filename.lower()
    content_type_lower = content_type.lower()
    
    text = None
    if filename_lower.endswith(".pdf") or "pdf" in content_type_lower:
        text = extract_pdf_text(file_path)
    elif filename_lower.endswith(".docx") or "officedocument.wordprocessingml" in content_type_lower:
        text = extract_docx_text(file_path)
    elif any(filename_lower.endswith(ext) for ext in [".txt", ".md", ".csv", ".json", ".markdown"]) or "text/" in content_type_lower:
        text = extract_txt_text(file_path)
    else:
        text = extract_txt_text(file_path)
        
    if not text:
        raise ValueError(f"Could not extract text from {filename}. File may be empty, unsupported, or corrupted.")
        
    return text

import asyncio
from bs4 import BeautifulSoup
import logging

def _extract_url_text_sync(url: str) -> str:
    """Synchronous worker that runs Playwright/Requests to deep-crawl up to 10 pages of the same domain."""
    from playwright.sync_api import sync_playwright
    import requests
    from urllib.parse import urlparse, urljoin
    from bs4 import BeautifulSoup
    
    base_domain = urlparse(url).netloc.replace("www.", "")
    visited_urls = set()
    urls_to_visit = [url]
    all_extracted_text = []
    
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    })

    def extract_text_and_links(html_str, page_url):
        soup = BeautifulSoup(html_str, "html.parser")
        
        # Extract links
        new_links = []
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith(('javascript:', 'mailto:', 'tel:', '#', 'viber:', 'whatsapp:')) or href.lower().endswith(('.pdf', '.png', '.jpg', '.zip', '.mp4')):
                continue
                
            full_link = urljoin(page_url, href).split('#')[0]
            link_domain = urlparse(full_link).netloc.replace("www.", "")
            
            # Allow subdomains by checking if base_domain is IN link_domain, or explicitly allow related Zenia products
            is_valid_domain = (base_domain in link_domain) or ("zeniahr.com" in link_domain) or ("zeniafleets.com" in link_domain) or ("tenderguruji.com" in link_domain)
            
            if is_valid_domain and full_link not in visited_urls and full_link not in urls_to_visit:
                new_links.append(full_link)
                
        # Clean up useless tags
        for element in soup(["script", "style", "meta", "noscript", "header", "footer", "nav", "svg", "iframe"]):
            element.decompose()
            
        return soup.get_text(separator="\n"), new_links

    max_pages = 20 # ADVANCED PRO: Crawl up to 20 internal pages
    
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            )
            page = context.new_page()
            
            while urls_to_visit and len(visited_urls) < max_pages:
                current_url = urls_to_visit.pop(0)
                if current_url in visited_urls:
                    continue
                    
                visited_urls.add(current_url)
                logger.info(f"[DEEP_CRAWLER] Crawling ({len(visited_urls)}/{max_pages}): {current_url}")
                
                try:
                    if "zeniahr.com" in current_url and len(visited_urls) == 1:
                        page.goto(current_url, timeout=40000, wait_until="networkidle")
                        if page.locator("button:has-text('Sign In'), button:has-text('Login')").count() > 0:
                            page.locator("input[type='email'], input[name='email'], [placeholder*='Email' i]").first.fill("om@gmail.com")
                            page.locator("input[type='password'], input[name='password'], [placeholder*='Password' i]").first.fill("password123")
                            page.locator("button:has-text('Sign In'), button:has-text('Login'), button[type='submit']").first.click()
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(3000)
                    else:
                        page.goto(current_url, timeout=30000, wait_until="networkidle")
                        
                    page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                    page.wait_for_timeout(1500) # Give React time to render JS
                    html_content = page.content()
                    
                    if html_content:
                        text, found_links = extract_text_and_links(html_content, current_url)
                        clean_text = normalize_extracted_text(text)
                        
                        # Only add if it has meaningful content
                        if clean_text and len(clean_text) > 20:
                            all_extracted_text.append(f"--- SOURCE URL: {current_url} ---\n{clean_text}")
                            
                        for link in found_links:
                            if link not in visited_urls and link not in urls_to_visit:
                                urls_to_visit.append(link)
                except Exception as e:
                    logger.warning(f"[DEEP_CRAWLER] Failed to crawl {current_url}: {e}")
            
            browser.close()
    except Exception as e:
        logger.error(f"[DEEP_CRAWLER] Critical failure during Playwright crawl: {e}")

    final_text = "\n\n".join(all_extracted_text)
    
    if not final_text or len(final_text) < 50:
        raise ValueError("Could not extract sufficient readable text from this URL.")
        
    return final_text

async def extract_url_text(url: str) -> str:
    """
    Bulletproof async wrapper for URL extraction. 
    Runs the synchronous Playwright code in a separate thread to avoid Windows/FastAPI loop conflicts.
    """
    try:
        # Run in a completely separate thread to avoid NotImplementedError on Windows asyncio subprocess
        return await asyncio.to_thread(_extract_url_text_sync, url)
    except Exception as e:
        logger.error(f"Failed to extract text from URL {url}: {e}")
        raise ValueError(f"URL content could not be read: {str(e)}")
