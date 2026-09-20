"""
Zenaipex AI — Language & Script Detector.

Detects the user''s language and script from a single message using:
  1. Unicode code-point ranges  (Devanagari, Gujarati, Bengali, etc.)
  2. Romanized Indian language word-list heuristics  (no API call)
  3. Conversation-history fallback for very short / ambiguous messages

Returns a LanguageResult that contains:
  - script   : "devanagari" | "gujarati_script" | "bengali" | "gurmukhi" |
                "tamil" | "telugu" | "kannada" | "malayalam" | "odia" |
                "arabic_urdu" | "latin"
  - lang     : "english" | "hindi" | "gujarati" | "marathi" | "bengali" |
                "punjabi" | "tamil" | "telugu" | "kannada" | "malayalam" |
                "urdu" | "nepali" | "odia" | "assamese" | "unknown"
  - style_instruction : str  (injected verbatim into the LLM system prompt)

No external packages required -- only Python stdlib.
"""
from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass, field
from typing import List, Dict, Optional


# Unicode block ranges (inclusive start/end code points)
_SCRIPT_RANGES = [
    (0x0900, 0x097F, "devanagari"),
    (0x0A80, 0x0AFF, "gujarati_script"),
    (0x0980, 0x09FF, "bengali"),
    (0x0A00, 0x0A7F, "gurmukhi"),
    (0x0B80, 0x0BFF, "tamil"),
    (0x0C00, 0x0C7F, "telugu"),
    (0x0C80, 0x0CFF, "kannada"),
    (0x0D00, 0x0D7F, "malayalam"),
    (0x0B00, 0x0B7F, "odia"),
    (0x0600, 0x06FF, "arabic_urdu"),
]


def _char_script(ch):
    cp = ord(ch)
    for start, end, name in _SCRIPT_RANGES:
        if start <= cp <= end:
            return name
    return None


def detect_script(text):
    counts = {}
    for ch in text:
        s = _char_script(ch)
        if s:
            counts[s] = counts.get(s, 0) + 1
    if not counts:
        return "latin"
    return max(counts, key=lambda k: counts[k])


# Romanized Indian language word signatures
_ROMANIZED_SIGNATURES = [
    ("gujarati", frozenset([
        "shu", "che", "kem", "cho", "tena", "pachi", "mane",
        "nathi", "ketlu", "hato", "thai", "thi", "vishe", "samjavo",
        "su", "thayu", "hatu", "hata", "hati", "chhe",
        "kai", "ane",
        "ketla", "ketli", "kya", "kyare", "tame", "ame", "mara", "tamara", 
        "karvu", "karie", "thase", "hase", "ravivar", "somvar", "mangalvar", 
        "budhvar", "guruvaar", "shukravar", "shanivar", "sukravar", "sanje", "vage", "avoto", "chalse"
    ]), 1),
    ("hindi", frozenset([
        "kya", "hai", "kaise", "mujhe", "nahi", "aur", "hain",
        "karein", "karo", "batao", "mein",
        "kon", "konsi", "konse", "kaunsi", "kaunse",
        "kyu", "kyun", "kyunki", "kab", "kahan", "kuch", "bahut",
        "accha", "theek", "sahi", "galat", "unhe", "unka",
        "hui", "hua", "hue", "bata", "bataiye", "samjhao",
        "kitna", "kitne", "chahiye", "milega", "karna", "aap", "tum",
        "kya hai", "kya time", "office time", "office kab"
    ]), 1),
    ("marathi", frozenset([
        "aahe", "ahe", "mhanaje", "aplya", "tyacha",
        "tyachi", "tyache", "sangaychay", "kasa", "kashi",
        "sangaa", "saanga",
    ]), 1),
    ("tamil", frozenset([
        "enna", "epdi", "nandri", "vanakkam", "sollunga", "theriyuma",
        "iruntha", "pannunga", "seyyungal",
    ]), 1),
    ("telugu", frozenset([
        "ela", "undi", "meeru", "mee", "cheppandi", "teliyadu",
        "enthi", "enti",
    ]), 1),
    ("kannada", frozenset([
        "hege", "enu", "nimage", "helri", "gottilla",
    ]), 1),
    ("malayalam", frozenset([
        "enthu", "anu", "cheyyuka", "ariyamo", "nanniyund",
    ]), 1),
    ("bengali", frozenset([
        "kemon", "achho", "bhalo", "korte", "bolun", "jani",
        "janina", "apni",
    ]), 1),
    ("punjabi", frozenset([
        "tussi", "tuhada", "kiddan", "dasao", "dasso",
    ]), 1),
]


def _tokenize(text):
    text_lower = text.lower()
    words = re.findall(r"[a-z'']+", text_lower)
    bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
    return words + bigrams


# Common English-only words -- if majority of a message is these, it is English.
# We use this as a veto against false positives from ambiguous Romanized-lang words.
_ENGLISH_COMMON = frozenset([
    "what", "how", "why", "where", "when", "which", "who",
    "does", "do", "did", "is", "are", "was", "were", "will",
    "the", "a", "an", "of", "in", "to", "for", "with", "on", "at",
    "and", "or", "but", "if", "by", "from", "this", "that", "it",
    "i", "you", "we", "they", "he", "she", "my", "your", "its",
    "can", "could", "should", "would", "have", "has", "had",
    "about", "explain", "tell", "describe", "show", "give", "list",
    "main", "features", "technologies", "technology", "use", "used",
    "please", "thanks", "okay", "yes", "no", "not", "like",
])


def detect_romanized_language(text):
    tokens = set(_tokenize(text))
    words_only = [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 1]
    if not words_only:
        return None
    # If >= 50% of the words are pure English common words, treat as English.
    english_hit_ratio = sum(1 for w in words_only if w in _ENGLISH_COMMON) / len(words_only)
    if english_hit_ratio >= 0.5:
        return None
    best_lang = None
    best_score = 0
    for lang, signature_words, min_hits in _ROMANIZED_SIGNATURES:
        hits = len(tokens & signature_words)
        if hits >= min_hits and hits > best_score:
            best_score = hits
            best_lang = lang
    return best_lang


_SCRIPT_TO_LANG = {
    "devanagari":      "hindi",
    "gujarati_script": "gujarati",
    "bengali":         "bengali",
    "gurmukhi":        "punjabi",
    "tamil":           "tamil",
    "telugu":          "telugu",
    "kannada":         "kannada",
    "malayalam":       "malayalam",
    "odia":            "odia",
    "arabic_urdu":     "urdu",
}

_NATIVE_SCRIPTS = {
    "devanagari", "gujarati_script", "bengali", "gurmukhi",
    "tamil", "telugu", "kannada", "malayalam", "odia", "arabic_urdu",
}

_FALLBACKS = {
    "english":         "I couldn't find the exact details for this information.",
    "hindi_latin":     "Mujhe is information ka exact detail nahi mila.",
    "hindi_native":    "\u092e\u0941\u091d\u0947 \u0907\u0938 \u091c\u093e\u0928\u0915\u093e\u0930\u0940 \u0915\u093e \u0938\u091f\u0940\u0915 \u0935\u093f\u0935\u0930\u0923 \u0928\u0939\u0940\u0902 \u092e\u093f\u0932\u093e\u0964",
    "gujarati_latin":  "Mane aa information ni exact detail mali nathi.",
    "gujarati_native": "\u0aae\u0aa8\u0ac7 \u0a86 \u0aae\u0abe\u0ab9\u0abf\u0aa4\u0ac0\u0aa8\u0ac0 \u0a9a\u0acb\u0a95\u0acd\u0a95\u0ab8 \u0ab5\u0abf\u0a97\u0aa4 \u0aae\u0ab3\u0ac0 \u0aa8\u0aa5\u0ac0.",
    "marathi_latin":   "Mala ya mahitichi nakki maahiti milali nahi.",
    "marathi_native":  "\u092e\u0932\u093e \u092f\u093e \u092e\u093e\u0939\u093f\u0924\u0940\u091a\u093e \u0928\u0915\u094d\u0915\u0940 \u0924\u092a\u0936\u0940\u0932 \u092e\u093f\u0933\u093e\u0932\u093e \u0928\u093e\u0939\u0940.",
    "bengali_latin":   "Ami ei tathyer sothik biboron khuje pailam na.",
    "bengali_native":  "\u0986\u09ae\u09bf \u098f\u0987 \u09a4\u09a5\u09cd\u09af\u09c7\u09b0 \u09b8\u09a0\u09bf\u0995 \u09ac\u09bf\u09ac\u09b0\u09a3 \u0996\u09c1\u0981\u099c\u09c7 \u09aa\u09c7\u09b2\u09be\u09ae \u09a8\u09be\u0964",
    "punjabi_latin":   "Main is jaankari di sahi detail nahi labbi.",
    "punjabi_native":  "\u0a2e\u0a48\u0a28\u0a42\u0a70 \u0a07\u0a38 \u0a1c\u0a3e\u0a23\u0a15\u0a3e\u0a30\u0a40 \u0a26\u0a40 \u0a38\u0a39\u0a40 \u0a1c\u0a3e\u0a23\u0a15\u0a3e\u0a30\u0a40 \u0a28\u0a39\u0a40\u0a02 \u0a2e\u0a3f\u0a32\u0a40\u0964",
    "tamil_latin":     "Enakku idhai pattru thunitha vivarangal kittavillai.",
    "tamil_native":    "\u0b87\u0ba8\u0bcd\u0ba4\u0bcd \u0ba4\u0b95\u0bb5\u0bb2\u0bc1\u0b95\u0bcd\u0b95\u0bbe\u0ba9 \u0b9a\u0bb0\u0bbf\u0baf\u0bbe\u0ba9 \u0bb5\u0bbf\u0bb5\u0bb0\u0b99\u0bcd\u0b95\u0bb3\u0bc8 \u0b8e\u0ba9\u0bcd\u0ba9\u0bbe\u0bb2\u0bcd \u0b95\u0ba3\u0bcd\u0b9f\u0bc1\u0baa\u0bbf\u0b9f\u0bbf\u0b95\u0bcd\u0b95 \u0bae\u0bc1\u0b9f\u0bbf\u0baf\u0bb5\u0bbf\u0bb2\u0bcd\u0bb2\u0bc8.",
    "telugu_latin":    "Naku ee samachara vivaragalu doraka ledhu.",
    "telugu_native":   "\u0c28\u0c3e\u0c15\u0c41 \u0c08 \u0c38\u0c2e\u0c3e\u0c1a\u0c3e\u0c30\u0c02 \u0c2f\u0c4a\u0c15\u0c4d\u0c15 \u0c16\u0c1a\u0c4d\u0c1a\u0c3f\u0c24\u0c2e\u0c48\u0c28 \u0c35\u0c3f\u0c35\u0c30\u0c3e\u0c32\u0c41 \u0c26\u0c4a\u0c30\u0c15\u0c32\u0c47\u0c26\u0c41.",
    "kannada_latin":   "Naanu ee mahiti nirdishta vivaragalannu kanda hididilla.",
    "kannada_native":  "\u0ca8\u0ca8\u0c97\u0cc6 \u0c88 \u0cae\u0cbe\u0cb9\u0cbf\u0ca4\u0cbf\u0caf \u0ca8\u0cbf\u0c96\u0cb0 \u0cb5\u0cbf\u0cb5\u0cb0\u0c97\u0cb3\u0cc1 \u0cb8\u0cbf\u0c97\u0cb2\u0cbf\u0cb2\u0ccd\u0cb2.",
    "malayalam_latin": "Ente ee vivaragal kittiyilla.",
    "malayalam_native":"\u0d08 \u0d35\u0d3f\u0d35\u0d30\u0d24\u0d4d\u0d24\u0d3f\u0d28\u0d4d\u0d31\u0d46 \u0d15\u0d43\u0d24\u0d4d\u0d2f\u0d2e\u0d3e\u0d2f \u0d35\u0d3f\u0d36\u0d26\u0d3e\u0d02\u0d36\u0d19\u0d4d\u0d19\u0d33\u0d4d\u200d \u0d0e\u0d28\u0d3f\u0d15\u0d4d\u0d15\u0d4d \u0d32\u0d2d\u0d3f\u0d1a\u0d4d\u0d1a\u0d3f\u0d32\u0d4d\u0d32.",
    "urdu_native":     "\u0645\u062c\u06be\u06d2 \u0627\u0633 \u0645\u0639\u0644\u0648\u0645\u0627\u062a \u06a9\u06cc \u062f\u0631\u0633\u062a \u062a\u0641\u0635\u06cc\u0644 \u0646\u06c1\u06cc\u06ba \u0645\u0644\u06cc\u06d4",
    "odia_native":     "\u0b2e\u0b41\u0b01 \u0b0f\u0b39\u0b3f \u0b38\u0b42\u0b1a\u0b28\u0b3e\u0b30 \u0b38\u0b20\u0b3f\u0b15 \u0b2c\u0b3f\u0b2c\u0b30\u0b23 \u0b16\u0b4b\u0b1c\u0b3f \u0b2a\u0b3e\u0b07\u0b32\u0b3f \u0b28\u0b3e\u0b39\u0b01\u0964",
}

_ERROR_FALLBACKS = {
    "english":         "I'm sorry, I'm having a temporary issue processing that request. Please try again in a moment.",
    "hindi_latin":     "Maaf kijiye, abhi request process karne mein temporary problem aa rahi hai. Kripya thodi der baad dobara try karein.",
    "hindi_native":    "\u092e\u093e\u092b\u093c \u0915\u0940\u091c\u093f\u090f, \u0905\u092d\u0940 \u0930\u093f\u0915\u094d\u0935\u0947\u0938\u094d\u091f \u092a\u094d\u0930\u094b\u0938\u0947\u0938 \u0915\u0930\u0928\u0947 \u092e\u0947\u0902 \u091f\u0947\u0902\u092a\u0930\u0947\u0930\u0940 \u092a\u094d\u0930\u0949\u092c\u094d\u0932\u092e \u0906 \u0930\u0939\u0940 \u0939\u0948\u0964 \u0915\u0943\u092a\u092f\u093e \u0925\u094b\u0921\u093c\u0940 \u0926\u0947\u0930 \u092c\u093e\u0926 \u0926\u094b\u092c\u093e\u0930\u093e \u091f\u094d\u0930\u093e\u0908 \u0915\u0930\u0947\u0902\u0964",
    "gujarati_latin":  "Maaf karjo, haal ma aa request process karva ma temporary problem aavi rahi che. Thodi vaar pachi fari try karo.",
    "gujarati_native": "\u0aae\u0abe\u0aab \u0a95\u0ab0\u0a9c\u0acb, \u0ab9\u0abe\u0ab2 \u0aae\u0abe\u0a82 \u0a86 \u0ab0\u0abf\u0a95\u0acd\u0ab5\u0ac7\u0ab8\u0acd\u0a9f \u0aaa\u0acd\u0ab0\u0acb\u0ab8\u0ac7\u0ab8 \u0a95\u0ab0\u0ab5\u0abe\u0aae\u0abe\u0a82 \u0a9f\u0ac7\u0aae\u0acd\u0aaa\u0ab0\u0ab0\u0ac0 \u0aaa\u0acd\u0ab0\u0acb\u0aac\u0acd\u0ab2\u0ac7\u0aae \u0a86\u0ab5\u0ac0 \u0ab0\u0ab9\u0ac0 \u0a9b\u0ac7. \u0aa5\u0acb\u0aa1\u0ac0 \u0ab5\u0abe\u0ab0 \u0aaa\u0a9b\u0ac0 \u0aab\u0ab0\u0ac0 \u0a9f\u0acd\u0ab0\u0abe\u0aaf \u0a95\u0ab0\u0acb.",
}

def _fallback(lang, script):
    suffix = "native" if script in _NATIVE_SCRIPTS else "latin"
    key = f"{lang}_{suffix}"
    return _FALLBACKS.get(key, _FALLBACKS.get(f"{lang}_latin", _FALLBACKS["english"]))

def _error_fallback(lang, script):
    suffix = "native" if script in _NATIVE_SCRIPTS else "latin"
    key = f"{lang}_{suffix}"
    return _ERROR_FALLBACKS.get(key, _ERROR_FALLBACKS.get(f"{lang}_latin", _ERROR_FALLBACKS["english"]))


def _build_instruction(lang, script):
    is_native = script in _NATIVE_SCRIPTS
    if lang == "english":
        return (
            "LANGUAGE & STYLE RULE (HIGHEST PRIORITY FOR FORMATTING):\n"
            "The user wrote in English. Respond in clear, natural English.\n"
            "Do NOT switch to Hindi, Gujarati, or any other language."
        )
    if is_native:
        display_map = {
            "devanagari":      "Hindi (Devanagari script)",
            "gujarati_script": "Gujarati (Gujarati script)",
            "bengali":         "Bengali (Bengali script)",
            "gurmukhi":        "Punjabi (Gurmukhi script)",
            "tamil":           "Tamil (Tamil script)",
            "telugu":          "Telugu (Telugu script)",
            "kannada":         "Kannada (Kannada script)",
            "malayalam":       "Malayalam (Malayalam script)",
            "odia":            "Odia (Odia script)",
            "arabic_urdu":     "Urdu (Nastaliq/Arabic script)",
        }
        display = display_map.get(script, lang.title())
        return (
            f"LANGUAGE & STYLE RULE (HIGHEST PRIORITY FOR FORMATTING):\n"
            f"The user wrote in {display}.\n"
            f"You MUST respond entirely in {display}.\n"
            f"Do NOT transliterate to Roman/Latin letters.\n"
            f"Preserve English technical terms (API names, product names, library names) in their original English form where natural.\n"
            f"Do NOT switch to English, Hindi, or any other language unless the user explicitly requests it.\n"
            f"If information is not available, respond with: \"{_fallback(lang, script)}\""
        )
    # Romanized
    examples_map = {
        "gujarati": "\"RitHan ek AI based web application che jo text thhi images generate kare che.\"",
        "hindi":    "\"RitHan ek AI based tool hai jo text se images generate karta hai.\"",
        "marathi":  "\"RitHan ek AI based application aahe jo text pasun images tayar karto.\"",
        "tamil":    "\"RitHan oru AI based application, idu text ilirundhu images create seyyum.\"",
        "telugu":   "\"RitHan oka AI based application, idi text nundi images create chestundi.\"",
        "kannada":  "\"RitHan ondu AI based application ide.\"",
        "malayalam":"\"RitHan oru AI based application aanu.\"",
        "bengali":  "\"RitHan ekta AI based web application, je text theke images toiri kore.\"",
        "punjabi":  "\"RitHan ik AI based web application hai jo text to images banaaunda hai.\"",
    }
    example = examples_map.get(lang, f"\"Answer naturally in Roman {lang.title()}.\"")
    return (
        f"LANGUAGE & STYLE RULE (HIGHEST PRIORITY FOR FORMATTING):\n"
        f"The user wrote in {lang.title()} using Roman/Latin letters (not native script).\n"
        f"You MUST respond in {lang.title()} using Roman/Latin letters -- do NOT use {lang.title()} native script.\n"
        f"Example style: {example}\n"
        f"Preserve English technical terms (API names, product names, library names) naturally.\n"
        f"Do NOT switch to English, Hindi, or any other language unless the user explicitly requests it.\n"
        f"If information is not available, respond with: \"{_fallback(lang, script)}\""
    )


@dataclass
class LanguageResult:
    lang: str
    script: str
    style_instruction: str
    fallback_message: str


def detect_language(text, conversation_history=None):
    """
    Detect language + script of `text`. Returns a LanguageResult.
    Detection order: native script -> romanized heuristic -> history fallback -> English.
    """
    text = (text or "").strip()

    # 1. Native script
    script = detect_script(text)
    if script != "latin":
        lang = _SCRIPT_TO_LANG.get(script, "unknown")
        return LanguageResult(
            lang=lang, script=script,
            style_instruction=_build_instruction(lang, script),
            fallback_message=_fallback(lang, script),
        )

    # 2. Romanized heuristic
    romanized_lang = detect_romanized_language(text)
    if romanized_lang:
        return LanguageResult(
            lang=romanized_lang, script="latin",
            style_instruction=_build_instruction(romanized_lang, "latin"),
            fallback_message=_fallback(romanized_lang, "latin"),
        )

    # 3. History fallback (for short follow-up messages <= 5 words)
    # IMPORTANT: only use history if the current message is NOT clearly English.
    # If the user explicitly switched to English, we must honor that switch even
    # if the prior turn was in another language.
    current_words = [w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 1]
    is_clearly_english = (
        len(current_words) > 0
        and sum(1 for w in current_words if w in _ENGLISH_COMMON) / len(current_words) >= 0.5
    )

    if len(text.split()) <= 5 and conversation_history and not is_clearly_english:
        for msg in reversed(conversation_history):
            if msg.get("role") == "user":
                prior_text = msg.get("content", "")
                prior_script = detect_script(prior_text)
                if prior_script != "latin":
                    prior_lang = _SCRIPT_TO_LANG.get(prior_script, "unknown")
                    return LanguageResult(
                        lang=prior_lang, script=prior_script,
                        style_instruction=_build_instruction(prior_lang, prior_script),
                        fallback_message=_fallback(prior_lang, prior_script),
                    )
                prior_rom = detect_romanized_language(prior_text)
                if prior_rom:
                    return LanguageResult(
                        lang=prior_rom, script="latin",
                        style_instruction=_build_instruction(prior_rom, "latin"),
                        fallback_message=_fallback(prior_rom, "latin"),
                    )
                break


    # 4. Default: English
    return LanguageResult(
        lang="english", script="latin",
        style_instruction=_build_instruction("english", "latin"),
        fallback_message=_FALLBACKS["english"],
    )


def get_fallback_message(lang, script):
    """Convenience wrapper for callers outside _build_messages."""
    return _fallback(lang, script)

def get_error_fallback_message(lang, script):
    return _error_fallback(lang, script)


# ─────────────────────────────────────────────────────────────────────────────
# Retrieval Query Normalizer
# ─────────────────────────────────────────────────────────────────────────────
# Maps common Romanized Indian language topic words/phrases → English equivalents
# used by the vector retrieval system.
# This is ONLY for search query normalization — NOT for output language.

_TOPIC_NORMALIZATIONS = [
    # Technology queries
    (r"\bkai technolog(?:y|ies)\b",    "technologies"),
    (r"\btechnolog(?:y|ies)\b",        "technologies"),
    (r"\bvapray\b|\bvapre\b",          "used"),
    (r"\buse thai che\b",              "is used"),
    (r"\buse che\b",                   "is used"),
    (r"\buse hui\b|\buse hain\b",      "is used"),
    (r"\bistemal\b",                   "used"),
    # Features
    (r"\bmukhya features?\b",          "main features"),
    (r"\bfeatures?\b",                 "features"),
    (r"\bvisheshtao\b|\bvisheshata\b", "features"),
    # What is
    (r"\bshu che\b",                   "what is"),
    (r"\bshu\b",                       "what"),
    (r"\bkya hai\b|\bkya he\b",        "what is"),
    (r"\bkay aahe\b|\bkay ahe\b",      "what is"),
    (r"\bema\b|\bma\b(?=\s)",          "in"),
    # scope / objective
    (r"\buddeshy[ao]\b|\blakshya\b",   "objectives"),
    # authentication / login
    (r"\bpramanikaran\b",              "authentication"),
    # database
    (r"\bdatabase\b|\bdata bhanda[rn]\b", "database"),
    # admin
    (r"\badmin panel\b",               "admin panel"),
    # common connectors — remove them (they don't help retrieval)
    (r"\bche\b|\bhai\b|\bhain\b|\baahe\b|\bahe\b", ""),
    (r"\bane\b|\baur\b|\bane\b|\bani\b",           "and"),
    (r"\btena\b|\biske\b|\buske\b|\btyacha\b",      "its"),
]

import re as _re


def normalize_query_for_retrieval(text: str) -> str:
    """
    Convert a Romanized Indian language query into a plain English equivalent
    suitable for vector retrieval against an English knowledge base.

    Examples:
        "RitHan ma kai technology use thai che?" -> "RitHan in technologies is used"
        "RitHan shu che?" -> "RitHan what is"
        "What technologies does RitHan use?" -> unchanged (already English)

    This is a RETRIEVAL-ONLY normalization. The output language of the final
    answer is determined separately by detect_language() and is NOT affected.
    """
    # If already English (no romanized signals), return as-is
    if detect_romanized_language(text) is None and detect_script(text) == "latin":
        return text

    normalized = text.lower()
    for pattern, replacement in _TOPIC_NORMALIZATIONS:
        normalized = _re.sub(pattern, replacement, normalized)

    # Clean up multiple spaces
    normalized = _re.sub(r"\s+", " ", normalized).strip()
    # Remove trailing punctuation
    normalized = normalized.rstrip("?!.,;")
    return normalized
