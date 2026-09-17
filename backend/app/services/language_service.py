"""Lightweight local language detection.

Detects the user's language from Unicode script ranges (authoritative for
Indic languages) plus a small stopword/hint lexicon for Romanized text
(Hinglish, Tanglish, etc.). Runs locally — no extra LLM call, per spec §12/§26.
"""

import re
from typing import Optional

# Unicode script ranges → ISO 639-1 code. Order matters: more specific
# scripts first. Devanagari is shared by Hindi/Marathi; Hindi is the common
# default (Marathi would need deeper lexical analysis).
_SCRIPT_RANGES: list[tuple[str, str]] = [
    ("bn", r"[\u0980-\u09FF]"),  # Bengali
    ("gu", r"[\u0A80-\u0AFF]"),  # Gujarati
    ("pa", r"[\u0A00-\u0A7F]"),  # Punjabi (Gurmukhi)
    ("ta", r"[\u0B80-\u0BFF]"),  # Tamil
    ("te", r"[\u0C00-\u0C7F]"),  # Telugu
    ("kn", r"[\u0C80-\u0CFF]"),  # Kannada
    ("ml", r"[\u0D00-\u0D7F]"),  # Malayalam
    ("hi", r"[\u0900-\u097F]"),  # Devanagari (Hindi default)
    ("ur", r"[\u0600-\u06FF]"),  # Arabic script (Urdu)
]

# Latin-script hints: common words with unambiguous language association.
# Kept intentionally small — used only when no native script is present.
_ROMANIZED_HINTS: dict[str, tuple[str, ...]] = {
    "hi": (
        "kya", "kaise", "kaisa", "kaisi", "kahan", "kab", "kaun", "kyun",
        "hai", "hoga", "hogi", "hain", "nahi", "nahin", "kar", "karo",
        "karna", "mujhe", "mera", "meri", "aaj", "kal", "barish", "baarish",
        "mausam", "garmi", "thand", "dhoop", "acha", "accha", "theek",
        "batao", "bata", "chahiye", "rahega", "rahegi", "hawa", "chahiye",
    ),
    "ta": ("enna", "eppadi", "irukku", "mazhai", "venum", "vendum", "ungal"),
    "te": ("ela", "undi", "untundi", "vartalu", "kavali", "naku"),
    "bn": ("ki", "kemon", "achhe", "hobe", "amake", "amar", "ajke"),
    "mr": ("kasa", "kashi", "ahe", "pahije", "mazha", "majha"),
}

# English words that frequently appear in mixed Hinglish messages; counting
# them keeps English dominant when a message is mostly English.
_ENGLISH_HINTS = (
    "the", "what", "how", "is", "will", "weather", "today", "tomorrow",
    "rain", "should", "carry", "umbrella", "wear", "good", "for", "in",
    "can", "you", "tell", "me", "about", "now", "like", "does", "do",
)

_WORD_RE = re.compile(r"[A-Za-z\u0900-\u097F\u0980-\u09FF\u0A00-\u0A7F"
                      r"\u0A80-\u0AFF\u0B80-\u0BFF\u0C00-\u0C7F"
                      r"\u0C80-\u0CFF\u0D00-\u0D7F\u0600-\u06FF]+")

# Language code → human name (for logs and status endpoint).
LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "bn": "Bengali",
    "ta": "Tamil",
    "te": "Telugu",
    "mr": "Marathi",
    "gu": "Gujarati",
    "kn": "Kannada",
    "ml": "Malayalam",
    "pa": "Punjabi",
    "ur": "Urdu",
}


def detect_language(text: str) -> str:
    """Detect the dominant language of *text*.

    Returns an ISO 639-1 code ('en', 'hi', ...). Native-script input is
    authoritative; Romanized input falls back to hint-word scoring with
    English as the neutral default.
    """
    if not text or not text.strip():
        return "en"

    # 1. Native script always wins (Hinglish with Devanagari → 'hi').
    for lang, pattern in _SCRIPT_RANGES:
        if re.search(pattern, text):
            return lang

    # 2. Romanized / Latin-script scoring.
    words = [w.lower() for w in _WORD_RE.findall(text)]
    if not words:
        return "en"

    scores: dict[str, int] = {}
    for word in words:
        for lang, hints in _ROMANIZED_HINTS.items():
            if word in hints:
                scores[lang] = scores.get(lang, 0) + 2

    english_hits = sum(1 for w in words if w in _ENGLISH_HINTS)
    best = max(scores.items(), key=lambda kv: kv[1]) if scores else None

    if best is not None and best[1] >= 2 and best[1] > english_hits:
        return best[0]
    return "en"


def language_name(code: Optional[str]) -> str:
    """Human-readable language name, safe for logs and status output."""
    if not code:
        return "English"
    return LANGUAGE_NAMES.get(code, code)
