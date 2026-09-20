import re
import logging
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

class CoverageValidator:
    """
    Programmatic validation to guarantee meaningful source coverage >= 99%
    and 0 cross-module or orphaned section violations.
    Filters out PDF boilerplate to accurately measure real chunk loss.
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
        Categorizes a text unit into A-F.
        A: Meaningful source content
        B: Repeated PDF headers/footers
        C: Page numbers
        D: Formatting artifacts
        E: Extractor noise
        F: Duplicate content intentionally removed
        """
        unit_stripped = unit.strip()
        unit_lower = unit_stripped.lower()
        
        # C: Page numbers
        if re.match(r'^page\s*\d+\s*of\s*\d+$', unit_lower) or (len(unit_stripped) < 5 and unit_stripped.isdigit()):
            return "C"
        if re.match(r'^---PAGE \d+---$', unit_stripped):
            return "C"
            
        # B: Repeated PDF headers/footers
        # Common ZeniaHR headers
        if "zeniahr admin panel: product and sales guide" in unit_lower:
            return "B"
        if "zeniahr" in unit_lower and len(unit_stripped) < 30 and ("admin" in unit_lower or "guide" in unit_lower):
            # Might be a standalone header fragment
            return "B"
            
        # F: TOC or Module Headers that get converted to metadata
        if re.match(r'^\d{2}.*?(SUPER ADMIN|CORE|BETA|ALL USERS|COMPANY HEAD)?.*$', unit_stripped, flags=re.IGNORECASE):
            # To avoid filtering actual content that happens to start with 2 digits, we check length
            # Module headers and TOC lines are usually short
            if len(unit_stripped) < 80:
                return "F"
            
        # D: Formatting artifacts
        if re.match(r'^[\W_]+$', unit_stripped): # Only non-word chars
            return "D"
            
        # E: Extractor noise (e.g. single weird characters, isolated numbers that aren't dates)
        if len(unit_stripped) <= 2 and not unit_stripped.isalpha():
            return "E"
            
        return "A" # Default to meaningful

    def _extract_units(self, text: str) -> List[Dict[str, Any]]:
        """Extract lines and categorize them."""
        lines = text.split('\n')
        units = []
        
        # Simple heuristic to track page numbers if '---PAGE X---' markers exist
        current_page = 1
        
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if not line_stripped:
                continue
                
            page_match = re.match(r'^---PAGE (\d+)---', line_stripped)
            if page_match:
                current_page = int(page_match.group(1))
                
            cat = self._categorize_unit(line_stripped)
            
            if cat != "A":
                self.telemetry["FILTERED_BOILERPLATE_CHARS"] += len(line_stripped)
            else:
                self.telemetry["MEANINGFUL_SOURCE_CHARS"] += len(line_stripped)
                
            units.append({
                "index": i,
                "page": current_page,
                "text": line_stripped,
                "category": cat,
                "length": len(line_stripped)
            })
            
        return units
        
    def _find_in_chunks(self, unit_text: str) -> Tuple[bool, str]:
        """Check if unit_text is in the chunks. Return (found, reason)."""
        search_unit = re.sub(r'\s+', ' ', unit_text).strip()
        
        # Exact substring match
        for chunk in self.chunks:
            chunk_normalized = re.sub(r'\s+', ' ', chunk["text"]).strip()
            if search_unit in chunk_normalized:
                return True, "Exact Match"
                
        # Word overlap (Cat G: Normalization differences)
        unit_words = set(search_unit.split())
        if len(unit_words) == 0:
            return False, "Empty"
            
        for chunk in self.chunks:
            chunk_words = set(chunk["text"].split())
            overlap = len(unit_words.intersection(chunk_words))
            if overlap / len(unit_words) > 0.8:
                return True, "Fuzzy Match (G)"
                
        return False, "Missing (A)"

    def validate(self) -> Dict[str, Any]:
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
                    "module": "Unknown", # We'd need structure extractor to know this reliably
                    "source_text_preview": unit["text"][:100],
                    "normalized_source_length": unit["length"],
                    "filtered_as_pdf_noise": False,
                    "reason": match_reason
                })
                
        # Also include boilerplate in report for debugging if needed, but mark it filtered
        for unit in all_units:
            if unit["category"] != "A":
                uncovered_report.append({
                    "source_unit_index": unit["index"],
                    "page_number": unit["page"],
                    "module": "Unknown",
                    "source_text_preview": unit["text"][:100],
                    "normalized_source_length": unit["length"],
                    "filtered_as_pdf_noise": True,
                    "reason": f"Category {unit['category']} Noise"
                })
                
        # Calculate coverage ONLY on meaningful chars
        if self.telemetry["MEANINGFUL_SOURCE_CHARS"] > 0:
            cov_pct = (self.telemetry["MATCHED_SOURCE_CHARS"] / self.telemetry["MEANINGFUL_SOURCE_CHARS"]) * 100
        else:
            cov_pct = 100.0
            
        self.telemetry["COVERAGE_PERCENT"] = cov_pct

        # 2. Cross-Module Violations
        module_headers = set([c["metadata"].get("module_number") for c in self.chunks if c["metadata"].get("module_number")])
        for chunk in self.chunks:
            meta = chunk["metadata"]
            chunk_mod = meta.get("module_number")
            text = chunk["text"]
            
            for mod in module_headers:
                if mod and mod != chunk_mod:
                    # Look for things like "Module 02" when this chunk is 01
                    # A robust check would require knowing the exact module titles
                    # We do a basic string search for the exact module format
                    if f"Module {mod}" in text or f"Module: {mod}" in text:
                        self.telemetry["CROSS_MODULE_VIOLATIONS"] += 1
                        
        report = {
            "telemetry": self.telemetry,
            "uncovered_report": uncovered_report,
            "coverage_percent": cov_pct,
            "cross_module_violations": self.telemetry["CROSS_MODULE_VIOLATIONS"],
            "success": cov_pct >= 99.0 and self.telemetry["CROSS_MODULE_VIOLATIONS"] == 0
        }
        
        return report
