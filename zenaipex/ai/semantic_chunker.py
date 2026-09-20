import re
import logging
import copy
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class SemanticChunker:
    """
    Production-grade, loss-minimizing semantic chunking system.
    Extracts headers, paragraphs, lists, and tabular data while preserving hierarchical context.
    Strictly enforces module boundaries, builds parent/child chunks, and adds contextual headers.
    """
    
    def __init__(self, max_chunk_size: int = 1500, overlap: int = 200):
        self.max_chunk_size = max_chunk_size
        self.overlap = overlap
        self.telemetry = {
            "cross_module_violations": 0,
            "heading_only_chunks": 0
        }

    def _clean_text(self, text: str) -> str:
        # Remove repetitive footers before chunking
        # Handles "ZeniaHR Admin Panel: Product and Sales Guide Page 4 of 73" with or without linebreaks.
        cleaned_text = re.sub(r'ZeniaHR\s+Admin\s+Panel:?\s*Product\s+and\s+Sales\s+Guide[\s\r\n]*Page\s+\d+(?:\s*of\s*\d+)?', '', text, flags=re.IGNORECASE)
        return cleaned_text

    def _parse_blocks(self, text: str) -> List[Dict[str, Any]]:
        """
        Extract meaningful semantic blocks from the raw text.
        Blocks can be: ModuleHeader, SectionHeader, Role, Description, Paragraph, List, Workflow, Table.
        """
        lines = [line.strip() for line in text.split('\n')]
        blocks = []
        current_page = 1
        
        current_list = []
        current_list_type = None # 'bullet', 'workflow', 'table' (approx)
        
        def push_list():
            if current_list:
                content = '\n'.join(current_list)
                if content.strip():
                    blocks.append({"type": current_list_type, "content": content, "page": current_page})
                current_list.clear()

        for line in lines:
            if not line:
                push_list()
                continue
                
            page_match = re.match(r'^---PAGE\s+(\d+)---$', line)
            if page_match:
                push_list()
                current_page = int(page_match.group(1))
                continue
                
            if len(line) < 20 and line.isdigit():
                continue
                
            # Module boundary check (e.g. "01 MODULE NAME")
            module_match = re.match(r'^(\d{2})\s*([A-Za-z].*?)(?:SUPER ADMIN|CORE|BETA|ALL USERS|COMPANY HEAD)?\s*$', line, flags=re.IGNORECASE)
            if module_match:
                name = module_match.group(2).strip()
                if re.search(r'\d+$', name) or re.search(r'\.{3,}', name) or len(name) > 40 or current_page <= 4:
                    pass # TOC entry or too long to be a header, let it fall through
                else:
                    push_list()
                    blocks.append({
                        "type": "ModuleHeader", 
                        "number": module_match.group(1), 
                        "name": name,
                        "page": current_page
                    })
                    continue

            if line.upper().startswith("ROLE:"):
                push_list()
                role_val = re.sub(r'^ROLE:\s*', '', line, flags=re.IGNORECASE).strip()
                blocks.append({"type": "Role", "content": role_val, "page": current_page})
                continue

            if line.upper().startswith("DESCRIPTION:"):
                push_list()
                blocks.append({"type": "Description", "content": line, "page": current_page})
                continue
                
            # Section headers
            section_match = line.upper() in ["KEY FEATURES AND OPTIONS", "HOW IT WORKS", "HOW IT CONNECTS TO OTHER MODULES", "SALES AND DEMO TIP"]
            if section_match or re.match(r'^#{1,6}\s+', line):
                push_list()
                section_name = re.sub(r'^#{1,6}\s+', '', line).strip() if not section_match else line.upper()
                blocks.append({"type": "SectionHeader", "content": section_name, "page": current_page})
                continue

            # Detect bullet lists (-, *, •)
            if re.match(r'^[-*•]\s+', line):
                if current_list_type != "List":
                    push_list()
                    current_list_type = "List"
                current_list.append(line)
                continue
                
            # Detect numbered workflows (1., 2., Step 1, etc.)
            if re.match(r'^(?:\d+\.|Step\s+\d+)\s+', line, flags=re.IGNORECASE):
                if current_list_type != "Workflow":
                    push_list()
                    current_list_type = "Workflow"
                current_list.append(line)
                continue

            # If inside a list/workflow, continuation line might not have a bullet
            if current_list_type in ["List", "Workflow"] and len(line) > 0 and not re.match(r'^[A-Z]', line) and current_list:
                current_list.append(line)
                continue
                
            # Table approximation (pipe separated or multiple tabs)
            if '|' in line or '\t' in line:
                if current_list_type != "Table":
                    push_list()
                    current_list_type = "Table"
                current_list.append(line)
                continue

            # Regular paragraph
            push_list()
            # If the last block is a paragraph on the same page, we might want to append, 
            # but it's safer to keep it separate and merge in the chunking phase
            if blocks and blocks[-1]["type"] == "Paragraph" and blocks[-1]["page"] == current_page:
                blocks[-1]["content"] += " " + line
            else:
                blocks.append({"type": "Paragraph", "content": line, "page": current_page})

        push_list()
        return blocks

    def _build_chunks_from_blocks(self, blocks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        chunks = []
        
        current_module_number = ""
        current_module_name = "General"
        current_role = ""
        current_section = "Overview"
        
        current_parent = []
        current_children = []
        
        def push_hierarchy(page_end: int):
            if not current_parent:
                return
                
            # Parent chunk
            parent_content = "\n\n".join(current_parent)
            parent_header = f"[Module: {current_module_number} {current_module_name} | Role: {current_role} | Section: {current_section}]"
            parent_text = f"{parent_header}\n\n{parent_content}"
            
            # Generate a consistent ID for the parent based on its metadata
            import hashlib
            parent_id = hashlib.md5(parent_text.encode('utf-8')).hexdigest()[:12]
            
            meta = {
                "module_number": current_module_number,
                "module_name": current_module_name,
                "role": current_role,
                "section": current_section,
                "subsection": "",
                "page_start": current_children[0]["page_start"] if current_children else page_end,
                "page_end": page_end,
                "content_type": "parent",
                "chunk_type": "parent",
                "parent_chunk_id": None,
                "parent_section": f"{current_module_number} {current_module_name}" if current_module_number else current_module_name
            }
            
            # Single child exact duplicate check
            if len(current_children) == 1:
                if len(parent_content.strip()) > 20:
                    single_meta = copy.deepcopy(meta)
                    single_meta["chunk_type"] = "parent" # eligible for parent resolution
                    single_meta["content_type"] = current_children[0]["type"]
                    chunks.append({"text": parent_text, "metadata": single_meta, "_internal_id": parent_id})
                else:
                    self.telemetry["heading_only_chunks"] += 1
            else:
                # Parent chunk
                if len(parent_content.strip()) > 20:
                    chunks.append({"text": parent_text, "metadata": meta, "_internal_id": parent_id})
                else:
                    self.telemetry["heading_only_chunks"] += 1

                # Child chunks
                child_index = 0
                for child in current_children:
                    child_text = child["content"]
                    if not child_text.strip():
                        continue
                        
                    # Split large children if they exceed max_chunk_size
                    if len(child_text) > self.max_chunk_size:
                        parts = self._split_large_text(child_text)
                        for part in parts:
                            child_full_text = f"{parent_header}\n\n{part}"
                            child_meta = copy.deepcopy(meta)
                            child_meta["chunk_type"] = "child"
                            child_meta["content_type"] = child["type"]
                            child_meta["parent_chunk_id"] = parent_id
                            child_meta["page_start"] = child["page_start"]
                            child_meta["page_end"] = child["page_end"]
                            chunks.append({"text": child_full_text, "metadata": child_meta})
                            child_index += 1
                    else:
                        child_full_text = f"{parent_header}\n\n{child_text}"
                        child_meta = copy.deepcopy(meta)
                        child_meta["chunk_type"] = "child"
                        child_meta["content_type"] = child["type"]
                        child_meta["parent_chunk_id"] = parent_id
                        child_meta["page_start"] = child["page_start"]
                        child_meta["page_end"] = child["page_end"]
                        chunks.append({"text": child_full_text, "metadata": child_meta})
                        child_index += 1
                    
            current_parent.clear()
            current_children.clear()

        for block in blocks:
            # Hierarchy boundaries
            if block["type"] == "ModuleHeader":
                push_hierarchy(block["page"])
                current_module_number = block["number"]
                current_module_name = block["name"]
                current_role = ""
                current_section = "Overview"
                
            elif block["type"] == "SectionHeader":
                push_hierarchy(block["page"])
                current_section = block["content"]
                
            elif block["type"] == "Role":
                current_role = block["content"]
                
            elif block["type"] in ["Paragraph", "Description", "List", "Workflow", "Table"]:
                content = block["content"]
                current_parent.append(content)
                current_children.append({
                    "content": content,
                    "type": block["type"],
                    "page_start": block["page"],
                    "page_end": block["page"]
                })
                
                # If parent gets too large, flush it to avoid giant parent chunks
                parent_len = sum(len(c) for c in current_parent)
                if parent_len > self.max_chunk_size * 2:
                    push_hierarchy(block["page"])

        push_hierarchy(blocks[-1]["page"] if blocks else 1)
        return chunks

    def _split_large_text(self, text: str) -> List[str]:
        words = text.split(' ')
        parts = []
        current = []
        current_len = 0
        for w in words:
            if current_len + len(w) > self.max_chunk_size and current:
                parts.append(' '.join(current))
                # Add overlap
                overlap_words = current[-30:] if len(current) > 30 else current
                current = overlap_words + [w]
                current_len = sum(len(x)+1 for x in current)
            else:
                current.append(w)
                current_len += len(w) + 1
        if current:
            parts.append(' '.join(current))
        return parts

    def chunk(self, text: str) -> List[Dict[str, Any]]:
        cleaned_text = self._clean_text(text)
        blocks = self._parse_blocks(cleaned_text)
        chunks = self._build_chunks_from_blocks(blocks)
        
        # Strip internal ids before returning
        for c in chunks:
            c.pop("_internal_id", None)
            
        return chunks

