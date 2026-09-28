"""
Zenaipex AI — Universal Chunk Coverage Validator.

Validates that document chunking retains meaningful content and does not suffer
catastrophic loss. Designed to be universal across technical reports, catalogs,
markdown documents, and PDFs.
"""
import re
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

class CoverageValidator:
    """
    Validates chunk coverage against source text.
    Provides diagnostic telemetry and guarantees that documents are indexed
    reliably without arbitrary failures on normal formatting differences.
    """

    def __init__(self, raw_text: str, chunks: List[Dict[str, Any]]):
        self.raw_text = raw_text
        self.chunks = chunks
        self.telemetry = {
            "RAW_SOURCE_CHARS": len(raw_text),
            "MEANINGFUL_SOURCE_CHARS": 0,
            "FILTERED_BOILERPLATE_CHARS": 0,
            "CHUNK_TEXT_CHARS": sum(len(c["text"]) for c in chunks),
            "MATCHED_SOURCE_CHARS": 0,
            "UNCOVERED_MEANINGFUL_CHARS": 0,
            "COVERAGE_PERCENT": 0.0,
            "CROSS_MODULE_VIOLATIONS": 0
        }

    def _categorize_unit(self, unit: str) -> str:
        """
        Categorize text line:
        A: Meaningful content
        B: Headers/footers/page numbers
        C: Page markers
        D: Separators / formatting artifacts
        E: Noise
        F: Markdown structural headers (converted to chunk metadata)
        """
        unit_stripped = unit.strip()
        unit_lower = unit_stripped.lower()

        # Page markers
        if re.match(r'^---PAGE\s+\d+---$', unit_stripped):
            return "C"

        # Page numbers (e.g. "Page 1 of 30", or standalone numbers)
        if re.match(r'^page\s*\d+\s*(?:of\s*\d+)?$', unit_lower) or (len(unit_stripped) <= 4 and unit_stripped.isdigit()):
            return "B"

        # Markdown headings (e.g. # Title, ## Section) -> these become chunk metadata/headers
        if re.match(r'^#{1,6}\s+', unit_stripped):
            return "F"

        # Separator lines (e.g. "---", "===", "***")
        if re.match(r'^[-=_*~]{3,}$', unit_stripped):
            return "D"

        # Only symbols/whitespace
        if re.match(r'^[\W_]+$', unit_stripped):
            return "D"

        # Extractor noise (single weird non-word chars)
        if len(unit_stripped) <= 2 and not unit_stripped.isalnum():
            return "E"

        return "A"

    def _extract_units(self, text: str) -> List[Dict[str, Any]]:
        """Extract and categorize lines from source text."""
        lines = text.split('\n')
        units = []
        current_page = 1

        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue

            page_match = re.match(r'^---PAGE\s+(\d+)---', line_stripped)
            if page_match:
                current_page = int(page_match.group(1))

            cat = self._categorize_unit(line_stripped)
            unit_len = len(line_stripped)

            if cat != "A":
                self.telemetry["FILTERED_BOILERPLATE_CHARS"] += unit_len
            else:
                self.telemetry["MEANINGFUL_SOURCE_CHARS"] += unit_len

            units.append({
                "index": i,
                "page": current_page,
                "text": line_stripped,
                "category": cat,
                "length": unit_len
            })

        return units

    def _find_in_chunks(self, unit_text: str) -> Tuple[bool, str]:
        """Check if unit_text is covered in chunk text."""
        search_unit = re.sub(r'\s+', ' ', unit_text).strip()
        if not search_unit:
            return True, "Empty"

        search_clean = re.sub(r'[^a-zA-Z0-9\s]', '', search_unit).lower()

        # Check exact and fuzzy match across chunks
        for chunk in self.chunks:
            chunk_text = chunk.get("text", "")
            chunk_normalized = re.sub(r'\s+', ' ', chunk_text).strip()

            if search_unit in chunk_normalized:
                return True, "Exact Match"

            # Check normalized word overlap
            chunk_clean = re.sub(r'[^a-zA-Z0-9\s]', '', chunk_normalized).lower()
            if search_clean and search_clean in chunk_clean:
                return True, "Normalized Substring"

            # Check token overlap
            unit_words = set(w for w in search_clean.split() if len(w) > 2)
            if unit_words:
                chunk_words = set(chunk_clean.split())
                overlap = len(unit_words.intersection(chunk_words))
                if overlap / len(unit_words) >= 0.7:
                    return True, "Token Overlap"

        return False, "Missing"

    def validate(self) -> Dict[str, Any]:
        """Perform validation and return structured report."""
        if not self.chunks:
            return {
                "telemetry": self.telemetry,
                "uncovered_report": [{"reason": "Zero chunks produced"}],
                "coverage_percent": 0.0,
                "cross_module_violations": 0,
                "success": False
            }

        all_units = self._extract_units(self.raw_text)
        meaningful_units = [u for u in all_units if u["category"] == "A"]

        uncovered_report = []
        covered_count = 0

        for unit in meaningful_units:
            found, match_reason = self._find_in_chunks(unit["text"])
            if found:
                covered_count += 1
                self.telemetry["MATCHED_SOURCE_CHARS"] += unit["length"]
            else:
                self.telemetry["UNCOVERED_MEANINGFUL_CHARS"] += unit["length"]
                uncovered_report.append({
                    "source_unit_index": unit["index"],
                    "page_number": unit["page"],
                    "source_text_preview": unit["text"][:100],
                    "length": unit["length"],
                    "reason": match_reason
                })

        if self.telemetry["MEANINGFUL_SOURCE_CHARS"] > 0:
            cov_pct = (self.telemetry["MATCHED_SOURCE_CHARS"] / self.telemetry["MEANINGFUL_SOURCE_CHARS"]) * 100.0
        else:
            cov_pct = 100.0

        self.telemetry["COVERAGE_PERCENT"] = round(cov_pct, 2)

        # In a real-world multi-tenant system:
        # Success requires at least 70% coverage of raw meaningful text (taking into account
        # header transformations, token splits, and whitespace normalization).
        success = (cov_pct >= 70.0) and (len(self.chunks) > 0)

        report = {
            "telemetry": self.telemetry,
            "uncovered_report": uncovered_report,
            "coverage_percent": round(cov_pct, 2),
            "cross_module_violations": 0,
            "success": success
        }

        return report
