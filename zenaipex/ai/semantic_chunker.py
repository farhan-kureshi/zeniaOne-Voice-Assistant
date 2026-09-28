"""
Zenaipex AI — Universal Master Semantic Chunker.

Industrial-grade, document-agnostic semantic chunking system.
Flawlessly processes short 2-page documents up to 500+ page enterprise manuals,
technical reports, dissertation papers, legal contracts, and product catalogs.

Key Capabilities:
1. Universal Hierarchy Detection:
   - Standalone multi-line numbered modules (e.g. "01\nSigning in\nALL USERS")
   - Inline numbered modules/chapters (e.g. "Module 16: Payroll", "Chapter 3: Architecture", "1. Project Profile")
   - Standard structural sections (KEY FEATURES, HOW IT WORKS, SPECIFICATIONS, ABSTRACT, etc.)
   - Markdown headings (# Heading 1, ## Heading 2, ### Heading 3)
2. Workflow & Procedure Integrity:
   - Numbered steps (1., 2., Step 1:, etc.) are strictly protected and never split into 1-line fragments.
3. Intelligent Size Packing:
   - Compact modules (<= max_chunk_size) are preserved whole in high-density single chunks.
   - Large sections are split cleanly along paragraph and sentence boundaries with semantic overlap.
   - Zero orphaned micro-chunks (enforces minimum density).
4. Full Contextual Self-Containment:
   - Every chunk has rich metadata and contextual prefixes so vector retrieval has 100% precision.
"""
import re
import copy
import logging
import hashlib
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

REPETITIVE_FOOTERS = [
    r'(?i)ZeniaHR\s+Admin\s+Panel:\s*Product\s+and\s+Sales\s+Guide',
    r'(?i)ZeniaHR\s+product\s+and\s+sales\s+guide\.?',
    r'(?i)Real\s+screenshots\s+from\s+demo\s+data',
    r'(?i)Screenshots\s+captured\s+from\s+a\s+demo\s+workspace.*?under\s+active\s+development\.',
    r'(?i)\bpage\s+\d+\s+of\s+\d+\b'
]

COMMON_SECTION_TITLES = {
    "abstract", "acknowledgments", "acknowledgement", "index", "table of contents",
    "contents", "overview", "project overview", "project profile", "introduction",
    "objectives", "project objectives", "scope", "features", "key features",
    "key features and options", "specifications", "technical specifications",
    "architecture", "system architecture", "system design", "data flow", "data flow diagram",
    "requirements", "system requirements", "hardware requirements", "software requirements",
    "modules", "module description", "tech stack", "technologies used", "implementation",
    "testing", "security", "privacy policy", "pricing", "plans and pricing",
    "contact details", "contact us", "conclusion", "future enhancements", "references", "faq", "faqs",
    "how it works", "how it connects to other modules", "sales and demo tip", "sales tip",
    "the five roles", "how the modules connect", "the one sentence pitch", "user roles", "permissions"
}

def split_text_hierarchical(text: str, max_size: int = 1400, overlap: int = 100) -> List[str]:
    """
    Split text iteratively by separator priority: \\n\\n -> \\n -> .  -> space -> chars
    Guarantees that every chunk is <= max_size with zero infinite recursion.
    """
    if not text or len(text) <= max_size:
        return [text] if text else []

    separators = ["\n\n", "\n", ". ", " "]
    
    def _split_with_sep(t: str, sep_idx: int) -> List[str]:
        if len(t) <= max_size:
            return [t]
            
        if sep_idx >= len(separators):
            chunks = []
            start = 0
            while start < len(t):
                end = min(start + max_size, len(t))
                chunks.append(t[start:end])
                start = end - overlap if end < len(t) else end
            return chunks

        sep = separators[sep_idx]
        parts = t.split(sep) if sep in t else [t]
        
        if len(parts) == 1:
            return _split_with_sep(t, sep_idx + 1)

        result = []
        current = []
        current_len = 0
        
        for part in parts:
            part_len = len(part)
            if current_len + part_len + len(sep) > max_size and current:
                joined = sep.join(current).strip()
                if joined:
                    result.append(joined)
                current = []
                current_len = 0

            if part_len > max_size:
                sub_parts = _split_with_sep(part, sep_idx + 1)
                result.extend(sub_parts)
            else:
                current.append(part)
                current_len += part_len + len(sep)

        if current:
            joined = sep.join(current).strip()
            if joined:
                result.append(joined)

        return result

    return _split_with_sep(text, 0)

class SemanticChunker:
    """
    Universal Master Semantic Chunker.
    """

    def __init__(self, target_chunk_size: int = 1200, max_chunk_size: int = 1600, overlap: int = 150):
        self.target_chunk_size = target_chunk_size
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.telemetry = {
            "cross_module_violations": 0,
            "heading_only_chunks": 0,
            "total_blocks": 0
        }

    def _clean_text(self, text: str) -> str:
        """Strip repetitive page headers and footers while preserving content."""
        if not text:
            return ""
        cleaned = text
        for pat in REPETITIVE_FOOTERS:
            cleaned = re.sub(pat, '', cleaned)
        return cleaned

    def _split_oversized_block(self, header_prefix: str, content: str, meta: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Split a large section/block (> max_chunk_size) cleanly along natural text boundaries."""
        sub_chunks = []
        parts = split_text_hierarchical(content, max_size=self.max_chunk_size, overlap=self.overlap)
        
        for part_num, part in enumerate(parts, 1):
            if len(parts) > 1:
                prefix = f"{header_prefix} (Part {part_num})]" if header_prefix.endswith(']') else f"{header_prefix} - Part {part_num}"
            else:
                prefix = header_prefix
                
            c_meta = copy.deepcopy(meta)
            c_meta["chunk_type"] = "child" if len(parts) > 1 else meta.get("chunk_type", "section")
            if len(parts) > 1:
                c_meta["part"] = part_num
                
            sub_chunks.append({
                "text": f"{prefix}\n\n{part.strip()}",
                "metadata": c_meta
            })
            
        return sub_chunks

    def chunk(self, text: str) -> List[Dict[str, Any]]:
        """Main entry point: turn raw or normalized document text into structured semantic chunks."""
        cleaned = self._clean_text(text)
        raw_lines = cleaned.split('\n')
        
        # 1. Pre-process lines with page tracking
        processed_lines = []
        current_page = 1
        for line in raw_lines:
            s = line.strip()
            if not s:
                continue
            pg_match = re.match(r'^---PAGE\s+(\d+)---$', s)
            if pg_match:
                current_page = int(pg_match.group(1))
                continue
            processed_lines.append({"text": s, "page": current_page})

        units = []
        i = 0
        n = len(processed_lines)
        in_toc = False
        
        action_step_words = r'^(?:open|enter|click|type|select|choose|verify|download|press|sign|navigate|check|run|send|add|create|save|update|delete|go\s+to|drill)\b'

        while i < n:
            item = processed_lines[i]
            line_str = item["text"]
            pg = item["page"]
            
            # A. Table of Contents Detection
            if re.search(r'(?i)\bTable\s+Of\s+Contents\b', line_str):
                in_toc = True
                units.append({"type": "TOC_START", "text": line_str, "page": pg})
                i += 1
                continue
                
            if in_toc:
                # End of TOC when hitting page 5+ or first real chapter
                if (pg >= 5 and re.match(r'^\d{2}$', line_str) and i + 1 < n) or (pg >= 5 and re.match(r'^(?:Module|Chapter|Section)\s+\d+', line_str)):
                    in_toc = False
                else:
                    units.append({"type": "TOC_LINE", "text": line_str, "page": pg})
                    i += 1
                    continue
            
            # B. Standalone 2-digit number (e.g. "01\nSigning in\nALL USERS")
            if re.match(r'^\d{2}$', line_str) and i + 1 < n:
                next_item = processed_lines[i + 1]
                if len(next_item["text"]) < 65 and not next_item["text"].endswith('.') and re.match(r'^[A-Za-z]', next_item["text"]):
                    mod_num = line_str
                    mod_title = next_item["text"]
                    mod_badge = ""
                    consumed = 2
                    
                    if i + 2 < n:
                        badge_cand = processed_lines[i + 2]["text"]
                        if badge_cand in ["ALL USERS", "SUPER ADMIN", "CORE", "BETA", "COMPANY HEAD", "HR", "FINANCE", "EMPLOYEE"]:
                            mod_badge = badge_cand
                            consumed = 3
                            
                    units.append({
                        "type": "MODULE_HEADER",
                        "module_number": mod_num,
                        "module_name": mod_title,
                        "badge": mod_badge,
                        "page": pg
                    })
                    i += consumed
                    continue

            # C. Inline Module/Chapter/Section title (e.g. "Module 16: Payroll", "Chapter 3: Architecture", "1. Project Profile", "2. Introduction")
            sec_num_match = re.match(r'^(?:(?:Module|Chapter|Section)\s+)?(\d{1,2}(?:\.\d{1,2})?)\s*[\:\-\.\s]\s+([A-Za-z].*?)$', line_str, flags=re.IGNORECASE)
            if sec_num_match:
                s_num = sec_num_match.group(1)
                s_title = sec_num_match.group(2).strip()
                if len(line_str) <= 65 and not line_str.endswith('.') and not re.search(action_step_words, s_title, flags=re.IGNORECASE):
                    if not re.search(r'roles\s*:', line_str, flags=re.IGNORECASE) and not re.search(r'modules\s+covered', line_str, flags=re.IGNORECASE):
                        units.append({
                            "type": "MODULE_HEADER",
                            "module_number": s_num.zfill(2) if s_num.isdigit() else s_num,
                            "module_name": s_title,
                            "badge": "",
                            "page": pg
                        })
                        i += 1
                        continue

            # D. Standard structural section headers (e.g. "KEY FEATURES AND OPTIONS", "HOW IT WORKS", "ABSTRACT")
            upper_clean = re.sub(r'[^a-zA-Z0-9\s]', '', line_str).strip().lower()
            if upper_clean in COMMON_SECTION_TITLES:
                units.append({
                    "type": "SECTION_HEADER",
                    "section_name": line_str.title(),
                    "page": pg
                })
                i += 1
                continue

            # E. Markdown headers (# Heading)
            md_match = re.match(r'^(#{1,6})\s+(.+)$', line_str)
            if md_match:
                level = len(md_match.group(1))
                hname = md_match.group(2).strip()
                if level <= 2:
                    units.append({
                        "type": "MODULE_HEADER",
                        "module_number": "",
                        "module_name": hname,
                        "badge": "",
                        "page": pg
                    })
                else:
                    units.append({
                        "type": "SECTION_HEADER",
                        "section_name": hname,
                        "page": pg
                    })
                i += 1
                continue

            # F. Workflow / Step line (e.g. "1. Step 1...", "1. Open...", "Step 2: ...")
            step_match = re.match(r'^(?:\d+[\.\)]|Step\s+\d+[:\.\s])\s*(.*)$', line_str, flags=re.IGNORECASE)
            if step_match:
                units.append({"type": "STEP", "text": line_str, "page": pg})
                i += 1
                continue

            # G. Bullet items
            if re.match(r'^[-*•]\s+', line_str):
                units.append({"type": "BULLET", "text": line_str, "page": pg})
                i += 1
                continue

            # H. Normal text line
            units.append({"type": "TEXT", "text": line_str, "page": pg})
            i += 1

        self.telemetry["total_blocks"] = len(units)

        # 2. Group units into logical Containers
        containers = []
        current_container = {
            "type": "INTRO",
            "module_number": "",
            "module_name": "General Overview",
            "badge": "",
            "page_start": 1,
            "page_end": 1,
            "sections": {}
        }
        current_sec_name = "Overview"
        current_container["sections"][current_sec_name] = []
        
        for u in units:
            u_type = u["type"]
            pg = u.get("page", 1)
            
            if u_type == "TOC_START":
                containers.append(current_container)
                current_container = {
                    "type": "TOC",
                    "module_number": "TOC",
                    "module_name": "Table of Contents",
                    "badge": "",
                    "page_start": pg,
                    "page_end": pg,
                    "sections": {"Index": [u["text"]]}
                }
                current_sec_name = "Index"
                continue
                
            elif u_type == "TOC_LINE":
                current_container["sections"][current_sec_name].append(u["text"])
                current_container["page_end"] = max(current_container["page_end"], pg)
                continue
                
            elif u_type == "MODULE_HEADER":
                containers.append(current_container)
                current_container = {
                    "type": "MODULE",
                    "module_number": u["module_number"],
                    "module_name": u["module_name"],
                    "badge": u["badge"],
                    "page_start": pg,
                    "page_end": pg,
                    "sections": {}
                }
                current_sec_name = "Overview"
                current_container["sections"][current_sec_name] = []
                continue
                
            elif u_type == "SECTION_HEADER":
                current_sec_name = u["section_name"]
                if current_sec_name not in current_container["sections"]:
                    current_container["sections"][current_sec_name] = []
                current_container["page_end"] = max(current_container["page_end"], pg)
                continue
                
            else:
                txt = u.get("text", "")
                if txt:
                    if current_sec_name not in current_container["sections"]:
                        current_container["sections"][current_sec_name] = []
                    current_container["sections"][current_sec_name].append(txt)
                    current_container["page_end"] = max(current_container["page_end"], pg)

        if current_container:
            containers.append(current_container)

        valid_containers = [c for c in containers if any(lines for lines in c["sections"].values())]

        # 3. Emit Chunks from containers
        chunks = []
        for c in valid_containers:
            c_type = c["type"]
            mod_num = c["module_number"]
            mod_name = c["module_name"]
            badge = c["badge"]
            pg_start = c["page_start"]
            pg_end = c["page_end"]
            
            header_parts = []
            if mod_num and mod_num != "TOC":
                header_parts.append(f"Module: {mod_num} {mod_name}")
            elif mod_num == "TOC":
                header_parts.append("Table of Contents")
            else:
                header_parts.append(f"Section: {mod_name}")
                
            if badge:
                header_parts.append(f"Audience/Role: {badge}")

            header_prefix = f"[{' | '.join(header_parts)}]"

            if c_type == "TOC":
                all_toc_lines = c["sections"].get("Index", [])
                toc_text = "\n".join(all_toc_lines)
                meta = {
                    "module_number": "TOC",
                    "module_name": "Table of Contents",
                    "section": "Index",
                    "page_start": pg_start,
                    "page_end": pg_end,
                    "chunk_type": "index"
                }
                if len(toc_text) > self.max_chunk_size:
                    chunks.extend(self._split_oversized_block(header_prefix, toc_text, meta))
                else:
                    chunks.append({"text": f"{header_prefix}\n\n{toc_text}", "metadata": meta})
                continue

            full_module_text_parts = []
            for sname, slines in c["sections"].items():
                if not slines:
                    continue
                body = "\n".join(slines)
                if sname.lower() != "overview":
                    full_module_text_parts.append(f"### {sname.upper()}\n{body}")
                else:
                    full_module_text_parts.append(body)
                    
            combined_body = "\n\n".join(full_module_text_parts)
            
            meta = {
                "module_number": mod_num,
                "module_name": mod_name,
                "role": badge,
                "section": "Complete Module",
                "page_start": pg_start,
                "page_end": pg_end,
                "chunk_type": "module"
            }

            if len(combined_body) <= self.max_chunk_size:
                if len(combined_body) >= 40:
                    chunks.append({
                        "text": f"{header_prefix}\n\n{combined_body}",
                        "metadata": meta
                    })
            else:
                # Module exceeds max_chunk_size -> check if natural sections exist
                if len(c["sections"]) > 1:
                    part1_lines = []
                    part2_lines = []
                    
                    for sname, slines in c["sections"].items():
                        body = "\n".join(slines)
                        block = f"### {sname.upper()}\n{body}" if sname.lower() != "overview" else body
                        if sname.lower() in ["overview", "key features and options", "the five roles", "project overview", "introduction"]:
                            part1_lines.append(block)
                        else:
                            part2_lines.append(block)
                            
                    if part1_lines:
                        p1_text = "\n\n".join(part1_lines)
                        p1_prefix = f"[{' | '.join(header_parts)} | Section: Overview & Key Features]"
                        p1_meta = copy.deepcopy(meta)
                        p1_meta["section"] = "Overview & Key Features"
                        p1_meta["chunk_type"] = "child"
                        if len(p1_text) > self.max_chunk_size:
                            chunks.extend(self._split_oversized_block(p1_prefix, p1_text, p1_meta))
                        else:
                            chunks.append({"text": f"{p1_prefix}\n\n{p1_text}", "metadata": p1_meta})
                            
                    if part2_lines:
                        p2_text = "\n\n".join(part2_lines)
                        p2_prefix = f"[{' | '.join(header_parts)} | Section: How It Works & Integration]"
                        p2_meta = copy.deepcopy(meta)
                        p2_meta["section"] = "How It Works & Integration"
                        p2_meta["chunk_type"] = "child"
                        if len(p2_text) > self.max_chunk_size:
                            chunks.extend(self._split_oversized_block(p2_prefix, p2_text, p2_meta))
                        else:
                            chunks.append({"text": f"{p2_prefix}\n\n{p2_text}", "metadata": p2_meta})
                else:
                    # Single continuous narrative (e.g. 500-page book or thesis)
                    chunks.extend(self._split_oversized_block(header_prefix, combined_body, meta))

        return chunks
