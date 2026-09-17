"""LLM orchestrator with automatic multi-provider fallback.

Implements spec §2/§3/§6/§7/§20/§21:
- configurable provider order (LLM_PROVIDER_ORDER env var)
- immediate fallback on rate-limit/quota, brief retry for transient errors
- exponential backoff for transient failures only
- provider cooldown (circuit breaker) after repeated failures
- automatic recovery after cooldown expiry
- safe structured logging (never logs keys)
"""

import asyncio
import time
from enum import Enum
from typing import Optional

from app.config import settings
from app.services.llm_providers import (
    ErrorKind,
    GeminiProvider,
    GroqProvider,
    LLMProvider,
    MistralProvider,
    ProviderError,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


class LLMError(Exception):
    """All providers failed, none configured, or the request itself is invalid."""


class ProviderState(str, Enum):
    """Internal provider health states (spec §6)."""

    AVAILABLE = "AVAILABLE"
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXHAUSTED = "QUOTA_EXHAUSTED"
    TEMPORARILY_UNAVAILABLE = "TEMPORARILY_UNAVAILABLE"
    INVALID_KEY = "INVALID_KEY"
    DISABLED = "DISABLED"
    NOT_CONFIGURED = "NOT_CONFIGURED"


# ErrorKind → provider state after a failure.
_FAILURE_STATE = {
    ErrorKind.RATE_LIMIT: ProviderState.RATE_LIMITED,
    ErrorKind.AUTH: ProviderState.INVALID_KEY,
    ErrorKind.SERVER: ProviderState.TEMPORARILY_UNAVAILABLE,
    ErrorKind.TIMEOUT: ProviderState.TEMPORARILY_UNAVAILABLE,
    ErrorKind.CONNECTION: ProviderState.TEMPORARILY_UNAVAILABLE,
    ErrorKind.BAD_RESPONSE: ProviderState.TEMPORARILY_UNAVAILABLE,
    ErrorKind.UNKNOWN: ProviderState.TEMPORARILY_UNAVAILABLE,
}

# Transient kinds get a short in-place retry with backoff before fallback;
# rate-limit/auth failures fallback immediately (spec §3).
_TRANSIENT_KINDS = {
    ErrorKind.SERVER,
    ErrorKind.TIMEOUT,
    ErrorKind.CONNECTION,
    ErrorKind.BAD_RESPONSE,
}


class _ProviderHealth:
    """Per-provider circuit-breaker state."""

    __slots__ = ("state", "consecutive_failures", "cooldown_until",
                 "last_error_kind")

    def __init__(self) -> None:
        self.state: ProviderState = ProviderState.AVAILABLE
        self.consecutive_failures: int = 0
        self.cooldown_until: float = 0.0
        self.last_error_kind: Optional[ErrorKind] = None

    def is_available(self, now: float) -> bool:
        """Eligible for selection: not in cooldown and not disabled."""
        if self.state == ProviderState.DISABLED:
            return False
        if self.state == ProviderState.NOT_CONFIGURED:
            return False
        if now < self.cooldown_until:
            return False
        # Cooldown expired → automatic recovery (spec §7).
        if self.state in (
            ProviderState.RATE_LIMITED,
            ProviderState.QUOTA_EXHAUSTED,
            ProviderState.TEMPORARILY_UNAVAILABLE,
            ProviderState.INVALID_KEY,
        ) and self.cooldown_until and now >= self.cooldown_until:
            self.state = ProviderState.AVAILABLE
            self.last_error_kind = None
        return self.state == ProviderState.AVAILABLE


class LLMManager:
    """Fallback orchestrator the rest of the app talks to (spec §4/§8)."""

    def __init__(self) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self._health: dict[str, _ProviderHealth] = {}
        self._order: list[str] = []
        self._lock = asyncio.Lock()
        self._build_providers()

    # ------------------------------------------------------------------ #
    # Construction / configuration
    # ------------------------------------------------------------------ #

    def _build_providers(self) -> None:
        self._providers = {
            "gemini": GeminiProvider(
                api_key=settings.gemini_api_key,
                model=settings.gemini_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_output_tokens=settings.llm_max_output_tokens,
            ),
            "mistral": MistralProvider(
                api_key=settings.mistral_api_key,
                model=settings.mistral_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_output_tokens=settings.llm_max_output_tokens,
            ),
            "groq": GroqProvider(
                api_key=settings.groq_api_key,
                model=settings.groq_model,
                timeout_seconds=settings.llm_timeout_seconds,
                max_output_tokens=settings.llm_max_output_tokens,
            ),
        }
        for name, provider in self._providers.items():
            if not provider.is_configured:
                self._health[name] = _ProviderHealth()
                self._health[name].state = ProviderState.NOT_CONFIGURED
            else:
                self._health[name] = _ProviderHealth()
        self._order = self._resolve_order()

    def _resolve_order(self) -> list[str]:
        """Provider order from settings; unknown names are ignored."""
        raw = settings.llm_provider_order or "gemini,mistral,groq"
        requested = [p.strip().lower() for p in raw.split(",") if p.strip()]
        order = [p for p in requested if p in self._providers]
        # Append any configured providers missing from the list (safety net).
        for name in self._providers:
            if name not in order:
                order.append(name)
        return order

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def generate(
        self,
        system_prompt: str,
        messages: list[dict],
        temperature: float = 0.7,
    ) -> tuple[str, str]:
        """Run a chat completion with automatic fallback.

        Returns ``(answer_text, provider_name)``.
        Raises :class:`LLMError` when every configured provider fails.
        """
        now = time.monotonic()
        candidates = [
            name for name in self._order
            if self._health[name].is_available(now)
            and self._providers[name].is_configured
        ]
        if not candidates:
            logger.warning("LLM generate: no providers currently available")
            raise LLMError("No LLM providers are currently available.")

        last_error: Optional[Exception] = None
        for index, name in enumerate(candidates):
            provider = self._providers[name]
            attempt = 0
            while True:
                attempt += 1
                started = time.perf_counter()
                try:
                    answer = await provider.generate(
                        system_prompt, messages, temperature
                    )
                    latency_ms = (time.perf_counter() - started) * 1000
                    self._on_success(name)
                    logger.info(
                        "LLM request | Provider: %s | Status: success | "
                        "Latency: %.0fms | Attempt: %d",
                        name, latency_ms, attempt,
                    )
                    return answer, name
                except ProviderError as exc:
                    latency_ms = (time.perf_counter() - started) * 1000
                    last_error = exc
                    self._on_failure(name, exc)
                    action = self._log_failure(name, exc, latency_ms, attempt)
                    if action == "retry":
                        backoff = self._backoff_seconds(attempt, exc)
                        await asyncio.sleep(backoff)
                        continue
                    if action == "abort":
                        # Invalid request — every provider would reject it
                        # identically; don't burn their quota (spec §1/§21).
                        raise LLMError(
                            f"LLM request rejected by {name} as invalid; "
                            f"not falling back: {exc}"
                        )
                    break  # fallback to next provider

            # If this was the last candidate, nothing more to try.
            if index == len(candidates) - 1:
                break

        raise LLMError(
            f"All LLM providers failed. Last error: {last_error}"
        )

    def has_available_provider(self) -> bool:
        """True when at least one provider is configured and not in cooldown."""
        now = time.monotonic()
        return any(
            self._health[name].is_available(now)
            and self._providers[name].is_configured
            for name in self._order
        )

    def get_status(self) -> dict:
        """Safe health snapshot — never includes keys (spec §6)."""
        now = time.monotonic()
        providers = {}
        for name in self._order:
            health = self._health[name]
            remaining = max(0.0, health.cooldown_until - now)
            providers[name] = {
                "configured": self._providers[name].is_configured,
                "state": health.state.value,
                "consecutive_failures": health.consecutive_failures,
                "cooldown_seconds_remaining": round(remaining, 1),
            }
        return {
            "provider_order": list(self._order),
            "providers": providers,
        }

    # ------------------------------------------------------------------ #
    # Failure handling / circuit breaker
    # ------------------------------------------------------------------ #

    def _on_success(self, name: str) -> None:
        health = self._health[name]
        health.consecutive_failures = 0
        health.cooldown_until = 0.0
        health.state = ProviderState.AVAILABLE

    def _on_failure(self, name: str, exc: ProviderError) -> None:
        health = self._health[name]
        health.consecutive_failures += 1
        health.last_error_kind = exc.kind

        if exc.kind == ErrorKind.RATE_LIMIT:
            # Distinguish quota exhaustion from momentary rate limits by
            # message content; the provider response stays authoritative.
            message = str(exc).lower()
            if "quota" in message or "exhausted" in message:
                health.state = ProviderState.QUOTA_EXHAUSTED
            else:
                health.state = ProviderState.RATE_LIMITED
            cooldown = self._cooldown_for(
                exc.retry_after, settings.llm_rate_limit_cooldown_seconds
            )
        elif exc.kind == ErrorKind.AUTH:
            # Invalid keys get a long cooldown so we probe occasionally
            # rather than permanently disabling (spec §7).
            health.state = ProviderState.INVALID_KEY
            cooldown = settings.llm_invalid_key_cooldown_seconds
        else:
            health.state = _FAILURE_STATE.get(
                exc.kind, ProviderState.TEMPORARILY_UNAVAILABLE
            )
            cooldown = 0.0  # recovered inline via retry/fallback
            if health.consecutive_failures >= settings.llm_max_consecutive_failures:
                cooldown = settings.llm_failure_cooldown_seconds

        if cooldown > 0:
            health.cooldown_until = time.monotonic() + cooldown

    def _cooldown_for(self, retry_after: Optional[float],
                      default: float) -> float:
        """Respect Retry-After when sane; otherwise use the default."""
        if retry_after is not None and 0 < retry_after <= 3600:
            return retry_after
        return default

    def _backoff_seconds(self, attempt: int, exc: ProviderError) -> float:
        """Exponential backoff for transient errors, capped (spec §3)."""
        base = min(2 ** (attempt - 1), 8)  # 1s, 2s, 4s, 8s cap
        if exc.kind == ErrorKind.TIMEOUT and exc.retry_after:
            base = max(base, min(exc.retry_after, 8))
        return base

    def _should_retry_inline(self, kind: ErrorKind, attempt: int) -> bool:
        """Short retry for transient errors only (spec §3/§21)."""
        if attempt >= settings.llm_max_transient_retries:
            return False
        return kind in _TRANSIENT_KINDS

    def _log_failure(self, name: str, exc: ProviderError,
                     latency_ms: float, attempt: int) -> str:
        """Log a safe failure line; returns the orchestrator action."""
        if exc.kind == ErrorKind.INVALID_REQUEST:
            # Our prompt/request bug — fallback would fail identically
            # everywhere, so don't waste the other providers' quota.
            logger.error(
                "LLM request | Provider: %s | Status: invalid_request | "
                "Latency: %.0fms | Action: abort (bug, not provider issue)",
                name, latency_ms,
            )
            return "abort"
        retry = self._should_retry_inline(exc.kind, attempt)
        action = "retry" if retry else "fallback"
        if retry:
            logger.warning(
                "LLM request | Provider: %s | Status: %s | Latency: %.0fms | "
                "Attempt: %d | Action: retry_after_backoff",
                name, exc.kind.value, latency_ms, attempt,
            )
        else:
            logger.warning(
                "LLM request | Provider: %s | Status: %s | Latency: %.0fms | "
                "Action: %s",
                name, exc.kind.value, latency_ms,
                f"fallback (cooldown {self._cooldown_for(exc.retry_after, settings.llm_rate_limit_cooldown_seconds):.0f}s)"
                if exc.kind == ErrorKind.RATE_LIMIT else
                f"fallback_to_next ({self._remaining_names(name)})",
            )
        return action

    def _remaining_names(self, failed: str) -> str:
        remaining = [
            n for n in self._order[self._order.index(failed) + 1:]
            if self._providers[n].is_configured
        ]
        return ",".join(remaining) if remaining else "none"


# Single shared instance — providers are stateless, health is process-wide.
llm_manager = LLMManager()
