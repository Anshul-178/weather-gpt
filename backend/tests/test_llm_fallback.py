"""Multi-LLM fallback and language detection tests (spec §24 LLM/Language)."""

import pytest

from app.services.llm_providers import (
    ErrorKind,
    LLMProvider,
    ProviderError,
    classify_exception,
)
from app.services.llm_manager import LLMError, LLMManager, ProviderState
from app.services.language_service import detect_language


# ------------------------------------------------------------------ #
# Error classification
# ------------------------------------------------------------------ #


def test_classify_429_is_rate_limit():
    exc = type("E", (Exception,), {})("429 too many requests")
    exc.status_code = 429
    kind = classify_exception(exc).kind
    assert kind == ErrorKind.RATE_LIMIT


def test_classify_503_is_server():
    exc = type("E", (Exception,), {})("service unavailable")
    exc.status_code = 503
    assert classify_exception(exc).kind == ErrorKind.SERVER


def test_classify_401_is_auth():
    exc = type("E", (Exception,), {})("unauthorized")
    exc.status_code = 401
    assert classify_exception(exc).kind == ErrorKind.AUTH


def test_classify_quota_text_without_status():
    exc = Exception("quota exceeded for this project")
    assert classify_exception(exc).kind == ErrorKind.RATE_LIMIT


def test_classify_timeout_text():
    assert classify_exception(Exception("request timed out")).kind == ErrorKind.TIMEOUT


# ------------------------------------------------------------------ #
# Provider base behaviour
# ------------------------------------------------------------------ #


class _StubProvider(LLMProvider):
    """Scriptable provider for orchestrator tests."""

    def __init__(self, name, failures=0, answer="ok"):
        super().__init__(api_key="test-key", model="m", timeout_seconds=5,
                         max_output_tokens=50)
        self.name = name
        self.calls = 0
        self._failures = failures
        self._answer = answer

    async def _generate(self, system_prompt, messages, temperature):
        self.calls += 1
        if self.calls <= self._failures:
            raise ProviderError(ErrorKind.RATE_LIMIT, f"{self.name}: 429")
        return self._answer


def _make_manager(*providers):
    manager = LLMManager.__new__(LLMManager)
    manager._providers = {p.name: p for p in providers}
    from app.services.llm_manager import _ProviderHealth
    manager._health = {p.name: _ProviderHealth() for p in providers}
    manager._order = list(manager._providers.keys())
    import asyncio
    manager._lock = asyncio.Lock()
    return manager


@pytest.mark.asyncio
async def test_first_provider_success_no_fallback():
    """Spec §26: 1 message → 1 LLM request normally."""
    first = _StubProvider("gemini", failures=0, answer="from gemini")
    second = _StubProvider("mistral", failures=0, answer="from mistral")
    manager = _make_manager(first, second)

    answer, provider = await manager.generate("sys", [{"role": "user", "content": "hi"}])
    assert answer == "from gemini"
    assert provider == "gemini"
    assert second.calls == 0


@pytest.mark.asyncio
async def test_rate_limit_falls_back_immediately():
    """Spec §24 LLM-2: Gemini 429 → Mistral attempted."""
    first = _StubProvider("gemini", failures=1, answer="from gemini")
    second = _StubProvider("mistral", failures=0, answer="from mistral")
    manager = _make_manager(first, second)

    answer, provider = await manager.generate("sys", [{"role": "user", "content": "hi"}])
    assert provider == "mistral"
    assert answer == "from mistral"
    # Immediate fallback: no wasteful re-calls of the rate-limited provider.
    assert first.calls == 1


@pytest.mark.asyncio
async def test_all_fail_raises_friendly_error():
    """Spec §24 LLM-5: all three fail → LLMError for the friendly message."""
    a = _StubProvider("gemini", failures=1)
    b = _StubProvider("mistral", failures=1)
    c = _StubProvider("groq", failures=1)
    manager = _make_manager(a, b, c)

    with pytest.raises(LLMError):
        await manager.generate("sys", [{"role": "user", "content": "hi"}])
    assert a.calls == 1 and b.calls == 1 and c.calls == 1


@pytest.mark.asyncio
async def test_unconfigured_provider_is_skipped():
    """Spec §24 LLM-7: no API key for one provider → skip it."""
    configured = _StubProvider("mistral", failures=0, answer="from mistral")
    manager = _make_manager(configured)
    manager._providers["gemini"] = _StubProvider("gemini")
    manager._providers["gemini"].api_key = None
    from app.services.llm_manager import _ProviderHealth
    manager._health["gemini"] = _ProviderHealth()
    manager._health["gemini"].state = ProviderState.NOT_CONFIGURED
    manager._order = ["gemini", "mistral"]

    answer, provider = await manager.generate("sys", [{"role": "user", "content": "hi"}])
    assert provider == "mistral"


@pytest.mark.asyncio
async def test_cooldown_prevents_hammering():
    """Spec §3/§7: after failure the provider cools down, then recovers."""
    provider = _StubProvider("gemini", failures=0, answer="ok")
    manager = _make_manager(provider)

    # Force a rate-limit failure → provider marked RATE_LIMITED with cooldown.
    import time as _time
    manager._health["gemini"].state = ProviderState.RATE_LIMITED
    manager._health["gemini"].cooldown_until = _time.monotonic() + 60.0

    # While in cooldown, provider is not eligible → no request is sent.
    assert not manager._health["gemini"].is_available(_time.monotonic())
    with pytest.raises(LLMError):
        await manager.generate("sys", [{"role": "user", "content": "hi"}])
    assert provider.calls == 0  # never hammered while rate-limited

    # Simulate cooldown expiry → automatic recovery (spec §7).
    manager._health["gemini"].cooldown_until = 0.0
    manager._health["gemini"].state = ProviderState.AVAILABLE
    answer, provider_name = await manager.generate("sys", [{"role": "user", "content": "hi"}])
    assert provider_name == "gemini"
    assert answer == "ok"


@pytest.mark.asyncio
async def test_invalid_request_aborts_without_fallback():
    """Spec §21: our own malformed request must not burn other providers."""
    from app.services.llm_providers import ProviderError as _PE

    class _BadRequest(_StubProvider):
        async def _generate(self, system_prompt, messages, temperature):
            self.calls += 1
            raise _PE(ErrorKind.INVALID_REQUEST, "bad request shape")

    first = _BadRequest("gemini")
    second = _StubProvider("mistral", failures=0)
    manager = _make_manager(first, second)

    with pytest.raises(LLMError):
        await manager.generate("sys", [{"role": "user", "content": "hi"}])
    assert second.calls == 0


def test_retry_after_header_respected():
    """Spec §21: Retry-After caps the rate-limit cooldown."""
    manager = LLMManager.__new__(LLMManager)
    assert manager._cooldown_for(30.0, 60.0) == 30.0
    assert manager._cooldown_for(99999.0, 60.0) == 60.0  # insane values ignored
    assert manager._cooldown_for(None, 60.0) == 60.0


# ------------------------------------------------------------------ #
# Language detection (spec §10-§12, §24 Language)
# ------------------------------------------------------------------ #


def test_detect_english():
    assert detect_language("What's the weather today?") == "en"


def test_detect_hindi_devanagari():
    assert detect_language("आज मौसम कैसा है?") == "hi"


def test_detect_hindi_with_english_word():
    """Hinglish in Devanagari: script wins (spec §10)."""
    assert detect_language("आज मौसम कैसा है Lucknow में?") == "hi"


def test_detect_romanized_hindi():
    assert detect_language("Aaj mausam kaisa hai?") == "hi"
    assert detect_language("क्या आज बारिश होगी?") == "hi"


def test_detect_romanized_hindi_mixed():
    """'mausam kaisa hai today' → Hindi dominant (spec §10)."""
    assert detect_language("mausam kaisa hai today?") == "hi"


def test_detect_english_mixed_with_hindi_word():
    """Mostly-English message with one Hindi word stays English."""
    assert detect_language("Will it rain today in Kanpur? aaj") == "en"


def test_detect_tamil_bengali():
    assert detect_language("இன்று வானிலை எப்படி இருக்கிறது?") == "ta"
    assert detect_language("আজ আবহাওয়া কেমন?") == "bn"


def test_detect_empty_is_english():
    assert detect_language("") == "en"
    assert detect_language("   ") == "en"
