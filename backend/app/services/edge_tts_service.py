"""Edge TTS service for natural neural Indian language speech synthesis.

Supports the multilingual requirement of the problem statement: Hindi,
Indian English, Tamil, Telugu, Bengali, Marathi, Kannada, Malayalam,
and Gujarati — auto-selected from the script of the text.
"""

import io
import re
from typing import Optional
import edge_tts

from app.utils.logging import get_logger

logger = get_logger(__name__)

# Microsoft Edge Neural voices for Indian languages.
VOICE_EN_IN = "en-IN-NeerjaNeural"        # Indian English Female
VOICE_EN_IN_MALE = "en-IN-PrabhatNeural"  # Indian English Male
VOICE_HI_IN = "hi-IN-SwaraNeural"         # Hindi Female
VOICE_HI_IN_MALE = "hi-IN-MadhurNeural"   # Hindi Male
VOICE_TA_IN = "ta-IN-PallaviNeural"       # Tamil Female
VOICE_TE_IN = "te-IN-ShrutiNeural"        # Telugu Female
VOICE_BN_IN = "bn-IN-TanishaaNeural"      # Bengali Female
VOICE_MR_IN = "mr-IN-AarohiNeural"        # Marathi Female
VOICE_KN_IN = "kn-IN-SapnaNeural"         # Kannada Female
VOICE_ML_IN = "ml-IN-SobhanaNeural"       # Malayalam Female
VOICE_GU_IN = "gu-IN-DhwaniNeural"        # Gujarati Female

# Unicode script ranges → default voice for each language. Devanagari is
# shared by Hindi and Marathi; Hindi is the common default and Marathi is
# selected explicitly via the language parameter.
SCRIPT_RANGES: list[tuple[str, str]] = [
    ("ta", r"[\u0B80-\u0BFF]"),   # Tamil
    ("te", r"[\u0C00-\u0C7F]"),   # Telugu
    ("bn", r"[\u0980-\u09FF]"),   # Bengali
    ("kn", r"[\u0C80-\u0CFF]"),   # Kannada
    ("ml", r"[\u0D00-\u0D7F]"),   # Malayalam
    ("gu", r"[\u0A80-\u0AFF]"),   # Gujarati
    ("hi", r"[\u0900-\u097F]"),   # Devanagari (Hindi default, Marathi shares script)
]

VOICES_BY_LANG: dict[str, str] = {
    "en": VOICE_EN_IN,
    "hi": VOICE_HI_IN,
    "ta": VOICE_TA_IN,
    "te": VOICE_TE_IN,
    "bn": VOICE_BN_IN,
    "mr": VOICE_MR_IN,
    "kn": VOICE_KN_IN,
    "ml": VOICE_ML_IN,
    "gu": VOICE_GU_IN,
}

# Explicit language selection (e.g. from the app's language picker) mapped
# to a voice, preferred over script auto-detection.
SUPPORTED_VOICES: dict[str, str] = {
    "en-IN": VOICE_EN_IN,
    "hi-IN": VOICE_HI_IN,
    "ta-IN": VOICE_TA_IN,
    "te-IN": VOICE_TE_IN,
    "bn-IN": VOICE_BN_IN,
    "mr-IN": VOICE_MR_IN,
    "kn-IN": VOICE_KN_IN,
    "ml-IN": VOICE_ML_IN,
    "gu-IN": VOICE_GU_IN,
}


def is_hindi(text: str) -> bool:
    """Detect if the string has Devanagari Hindi characters."""
    return bool(re.search(r"[\u0900-\u097F]", text))


def detect_language(text: str) -> str:
    """Detect the Indian language of a text by its Unicode script."""
    for lang, pattern in SCRIPT_RANGES:
        if re.search(pattern, text):
            return lang
    return "en"


def clean_tts_text(text: str) -> str:
    """Strip markdown symbols and URLs for smooth text-to-speech pronunciation."""
    cleaned = re.sub(r"(\*\*|__|\*|_|#|`|~)", "", text)
    cleaned = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", cleaned)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = re.sub(r"\n+", " ", cleaned)
    return cleaned.strip()


class EdgeTtsService:
    """High quality Microsoft Edge Neural Text-to-Speech synthesis."""

    async def synthesize_speech(
        self,
        text: str,
        voice: Optional[str] = None,
        language: Optional[str] = None,
        rate: str = "+0%",
        pitch: str = "+0Hz",
    ) -> bytes:
        """Synthesize text into MP3 audio bytes using Edge TTS.

        Voice resolution order: explicit voice name > explicit language code >
        script auto-detection > Indian English.
        """
        cleaned = clean_tts_text(text)
        if not cleaned:
            return b""

        if voice is None:
            if language and language in SUPPORTED_VOICES:
                voice = SUPPORTED_VOICES[language]
            else:
                voice = VOICES_BY_LANG.get(detect_language(cleaned), VOICE_EN_IN)

        logger.info(
            "Synthesizing Edge TTS with voice: %s, text length: %d", voice, len(cleaned)
        )

        communicate = edge_tts.Communicate(
            text=cleaned,
            voice=voice,
            rate=rate,
            pitch=pitch,
        )

        audio_buffer = io.BytesIO()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.write(chunk["data"])

        return audio_buffer.getvalue()


edge_tts_service = EdgeTtsService()
