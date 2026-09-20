import asyncio
import logging
from typing import Any

from zenaipex.services.knowledge_service import extract_text
from zenaipex.ai.semantic_chunker import SemanticChunker
from zenaipex.ai.chunk_validator import CoverageValidator
import sys
import json

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main(pdf_path: str):
    logger.info(f"Extracting text from {pdf_path}...")
    try:
        content = extract_text(pdf_path, "ZeniaHR-Admin-Guide.pdf", "application/pdf")
    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        return
        
    logger.info(f"Extracted {len(content)} characters. Running SemanticChunker...")
    
    chunker = SemanticChunker(max_chunk_size=1500)
    chunk_dicts = chunker.chunk(content)
    logger.info(f"Generated {len(chunk_dicts)} chunks.")
    
    logger.info("Running CoverageValidator...")
    validator = CoverageValidator(content, chunk_dicts)
    val_report = validator.validate()
    
    telemetry = val_report.get("telemetry", {})
    
    logger.info("\n=== TELEMETRY ===")
    for k, v in telemetry.items():
        logger.info(f"{k}: {v}")
        
    uncovered = [u for u in val_report.get("uncovered_report", []) if not u.get("filtered_as_pdf_noise")]
    
    logger.info(f"\n=== UNCOVERED REPORT ({len(uncovered)} ITEMS) ===")
    for u in uncovered[:20]:
        logger.warning(f"Pg {u['page_number']} | Idx {u['source_unit_index']} | {u['reason']}: {u['source_text_preview']}")
        
    if len(uncovered) > 20:
        logger.warning(f"... and {len(uncovered) - 20} more.")
        
    logger.info(f"\nSuccess: {val_report['success']}")
    
if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        print("Usage: python run_validator_diagnostic.py <path_to_pdf>")
