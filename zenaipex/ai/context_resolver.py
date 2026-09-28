"""
Step 6: Contextual Follow-up Resolver

Lightweight deterministic module (NO LLM calls) that:
1. Detects short contextual follow-ups ("tell me more", "aur batao", etc.)
2. Resolves the subject from the most recent conversation turn
3. Routes to expanded fast-path or rewrites query for RAG

This eliminates unnecessary Intent LLM + RAG calls for obvious follow-ups.
"""
import re
import time
import logging
from collections import OrderedDict
from typing import Optional, Dict, Any, Tuple, List

logger = logging.getLogger(__name__)

# ── Follow-up Detection Patterns ──────────────────────────────────────────────
# These patterns match short contextual follow-ups where "it"/"this" refers
# to the immediately previous subject. No LLM needed to resolve these.

_FOLLOWUP_PATTERNS = re.compile(
    r"^("
    # English
    r"tell\s+me\s+more(?:\s+about\s+(?:it|this|that))?"
    r"|explain\s+(?:more|that|it|this|in\s+detail|deeply)?"
    r"|more\s+details?"
    r"|more\s+about\s+(?:it|this|that)"
    r"|what\s+(?:about|else)\s+(?:it|this|that)"
    r"|go\s+on"
    r"|continue"
    r"|elaborate"
    r"|can\s+you\s+(?:explain|tell)\s+more"
    r"|what\s+more\s+can\s+you\s+tell\s+me"
    r"|(?:in\s+)?details?(?:\s+deep)?"
    r"|(?:in\s+)?deep(?:\s+details?)?"
    r"|deep\s+explanation"
    r"|deeply"
    r"|in\s+depth"
    # Hindi / Hinglish / Gujarati
    r"|aur\s+batao"
    r"|aur\s+bataye"
    r"|aur\s+bata(?:\s+do)?"
    r"|thod[ia]\s+(?:detail|aur)"
    r"|iske?\s+(?:baare?\s+me(?:in)?(?:\s+(?:aur\s+)?(?:batao|bataye|samjhao|jaankari|detail|details|information))?|features?\s+(?:aur\s+)?batao)"
    r"|uske?\s+(?:baare?\s+me(?:in)?(?:\s+(?:aur\s+)?(?:batao|bataye|samjhao|jaankari|detail|details|information))?|features?\s+(?:aur\s+)?batao)"
    r"|isme?\s+aur\s+kya\s+hai"
    r"|aur\s+samjhao"
    r"|aur\s+jaankari"
    r"|aur\s+(?:details?|information)(?:\s+(?:batao|samjhao))?"
    r"|iske?\s+(?:features?|modules?)\s+(?:kya\s+hain|batao|aur\s+batao)"
    r"|aur\s+(?:kya|kuch)\s+batao"
    r"|vistar\s+se\s+batao"
    r"|vistar\s+thi\s+(?:samjavo|janavo)"
    r"|detail\s+me(?:in)?\s+batao"
    r"|deep\s+me(?:in)?\s+samjhao"
    r"|kya\s+kya\s+features?\s+h(?:ai|e)(?:\s+isme(?:in)?)?"
    r"|konse\s+konse\s+features?\s+h(?:ai|e)(?:\s+isme(?:in)?)?"
    r"|isme(?:in)?\s+kya\s+kya\s+h(?:ai|e)"
    r"|what\s+features?\s+(?:does\s+(?:it|this)\s+have|are\s+there)"
    r")$",
    re.IGNORECASE
)

# ── Explicit Feature Query Routing ───────────────────────────────────────────
# Deterministic RAG routing for full feature questions to bypass LLM
_FEATURE_PATTERNS = re.compile(
    r"^(?:kya\s+kya\s+features\s+h(?:ai|e)|konse\s+konse\s+features\s+h(?:ai|e)|what\s+features\s+does)(?:\s+(zeniaone|zeniahr|zinnia\s+one|zenia\s+one|zenya\s+one|janya\s+one|janya|zinnia|zenia|rithan|rithan\s+ai|it|this))?(?:\s+(?:me|have|ma|ni))?$|"
    r"^(zeniaone|zeniahr|zinnia\s+one|zenia\s+one|zenya\s+one|janya\s+one|janya|zinnia|zenia|rithan|rithan\s+ai|it|this)(?:\s+(?:ke|na|me|ma))?\s+(?:kya\s+kya\s+h(?:ai|e)|features\s+batao|kya\s+kya\s+features\s+(?:h(?:ai|e)|che|chhe)|kaya\s+kaya\s+features\s+(?:che|chhe)|features\s+vishe\s+janavo|features\s+kya\s+hain)$|"
    r"^(what\s+are\s+the\s+features\s+of|features\s+of)\s+(zeniaone|zeniahr|zinnia\s+one|zenia\s+one|zenya\s+one|janya\s+one|janya|zinnia|zenia|rithan|rithan\s+ai|it|this)$",
    re.IGNORECASE
)

# ── Subject Extraction ────────────────────────────────────────────────────────
# Known product/module entities that can be tracked as conversation subjects

_KNOWN_SUBJECTS = {
    "zeniaone": "ZeniaOne",
    "zeniahr": "ZeniaHR",
    "zenia one": "ZeniaOne",
    "zenia hr": "ZeniaHR",
    "zinnia one": "ZeniaOne",
    "zinnia hr": "ZeniaHR",
    "zenya one": "ZeniaOne",
    "zenya hr": "ZeniaHR",
    "janya one": "ZeniaOne",
    "janya hr": "ZeniaHR",
    "janya": "ZeniaOne",
    "zinnia": "ZeniaOne",
    "zenia": "ZeniaOne",
    "rithan": "RitHan AI",
    "rithan ai": "RitHan AI",
    "attendance": "attendance",
    "payroll": "payroll",
    "leave": "leave policy",
    "leave policy": "leave policy",
    "salary": "payroll",
    # Step 8B: Expanded supported KB topics
    "recruitment": "Recruitment",
    "hiring": "Recruitment",
    "finance": "Finance",
    "performance": "Performance",
    "appraisal": "Performance",
    "employees": "Employees",
    "employee": "Employees",
    "settings": "Settings",
}

# ── Conversation Subject State ────────────────────────────────────────────────
# Bounded OrderedDict keyed by conversation_id → {"subject": str, "timestamp": float}
# Capped at 500 entries with LRU eviction.

_MAX_SUBJECTS = 500
_conversation_subjects: OrderedDict = OrderedDict()


def _evict_if_needed():
    """LRU eviction when subject cache exceeds bound."""
    while len(_conversation_subjects) > _MAX_SUBJECTS:
        _conversation_subjects.popitem(last=False)


def record_subject(conversation_id: Optional[str], response_text: str, user_message: str):
    """
    Extract and store the primary subject from the current turn.
    Called after every response is generated (fast-path or LLM).
    """
    if not conversation_id:
        return

    subject = None
    msg_lower = user_message.lower().strip()

    # 1. Check if user message explicitly mentions a known subject
    for pattern, canonical in _KNOWN_SUBJECTS.items():
        if pattern in msg_lower:
            subject = canonical
            break

    # 2. If no known subject found, try to extract from the user's question structure
    #    e.g., "What is X?" → subject = X
    if not subject:
        m = re.match(r"^(?:what\s+is|what'?s|tell\s+me\s+about|explain)\s+(.+?)[\?\.]?$", msg_lower)
        if m:
            candidate = m.group(1).strip()
            if len(candidate) < 50 and candidate not in ("it", "this", "that"):
                subject = candidate

    if subject:
        _conversation_subjects[conversation_id] = {
            "subject": subject,
            "timestamp": time.time(),
            "source_message": user_message,
        }
        # Move to end (most recent)
        _conversation_subjects.move_to_end(conversation_id)
        _evict_if_needed()
        logger.debug(f"[CONTEXT_SUBJECT] conv={conversation_id} subject={subject}")
        logger.info(f"[CONTEXT_SUBJECT_RESOLVED] subject={subject} source=deterministic")


def resolve_followup(
    message: str,
    conversation_id: Optional[str],
    history: List[Dict[str, str]],
    company: Dict[str, Any],
    agent: Dict[str, Any],
    detected_lang: str,
    detected_script: str,
) -> Optional[Dict[str, Any]]:
    """
    Check if the message is a short contextual follow-up and resolve it.

    Returns:
        None if not a follow-up or can't resolve
        Dict with keys:
            - "response": str (if deterministic answer available)
            - "rewritten_query": str (if RAG retrieval needed)
            - "resolved_subject": str
            - "intent": str
    """
    import string
    msg_clean = message.lower().strip()
    msg_no_punct = msg_clean.translate(str.maketrans('', '', string.punctuation)).strip()

    # 1. Is this an explicit feature query?
    feat_match = _FEATURE_PATTERNS.match(msg_no_punct)
    if feat_match:
        # Extract explicit subject if present
        subject = None
        for group in feat_match.groups():
            if group and group.lower() in _KNOWN_SUBJECTS:
                subject = _KNOWN_SUBJECTS[group.lower()]
                break
        
        # If no explicit subject, try to get from history
        if not subject and conversation_id and conversation_id in _conversation_subjects:
            subject = _conversation_subjects[conversation_id]["subject"]
            
        if not subject:
            subject = "ZeniaOne" # Default to primary product if context lost
            
        rewritten = f"{subject} features and capabilities"
        logger.info(f"[CONTEXT_RESOLVER] explicit_feature_detected=true subject={subject} rewrite='{rewritten}' intent_skipped=true")
        return {
            "rewritten_query": rewritten,
            "resolved_subject": subject,
            "intent": "document_query",
        }

    # 1. Is this a follow-up pattern?
    if not _FOLLOWUP_PATTERNS.match(msg_no_punct):
        return None

    # 2. Do we have a stored subject for this conversation?
    subject_data = None
    if conversation_id and conversation_id in _conversation_subjects:
        subject_data = _conversation_subjects[conversation_id]

    # 3. If no stored subject, try extracting from history
    if not subject_data and history:
        # Look at last user message for subject clues
        for msg in reversed(history):
            if msg.get("role") == "user":
                user_msg = msg.get("content", "").lower()
                for pattern, canonical in _KNOWN_SUBJECTS.items():
                    if pattern in user_msg:
                        subject_data = {"subject": canonical, "source_message": msg.get("content", "")}
                        break
                if subject_data:
                    break

    if not subject_data:
        logger.info(f"[CONTEXT_RESOLVER] followup_detected=true subject_found=false message='{message}' action=fallthrough")
        return None

    subject = subject_data["subject"]
    logger.info(f"[CONTEXT_RESOLVER] followup_detected=true subject={subject} message='{message}' intent_skipped=true")

    # 4. Check if expanded fast-path can answer
    from ai.fast_path import check_deterministic_fast_path

    # Construct an explicit expanded query
    expanded_queries = [
        f"What is {subject}?",
        f"Tell me more about {subject}",
        f"{subject} features kya hain",
    ]

    for eq in expanded_queries:
        fast_resp = check_deterministic_fast_path(eq, company, agent, detected_lang, detected_script)
        if fast_resp:
            logger.info(f"[CONTEXT_RESOLVER] route=FAST_PATH subject={subject} rewrite='{eq}' llm_called=false rag_called=false")
            return {
                "response": fast_resp,
                "resolved_subject": subject,
                "intent": "context_followup_fast",
                "rewritten_query": eq,
            }

    # 5. No fast-path → rewrite for RAG retrieval
    rewritten = f"{subject} details"
    logger.info(f"[CONTEXT_RESOLVER] route=RAG_REWRITE subject={subject} rewrite='{rewritten}' intent_skipped=true")
    return {
        "rewritten_query": rewritten,
        "resolved_subject": subject,
        "intent": "document_query",
    }
