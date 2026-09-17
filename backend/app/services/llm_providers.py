"""LLM provider abstraction: Gemini, Mistral, Groq.

Each provider wraps its SDK behind a common async ``generate`` interface and
translates low-level errors into a normalised :class:`ProviderError` carrying
an :class:`ErrorKind` so the orchestrator can decide between
retry / fallback / skip without knowing SDK specifics.
"""

import asyncio
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

from app.utils.logging import get_logger

logger = get_logger(__name__)


class ErrorKind(str, Enum):
    """Normalised classification of provider failures."""

    RATE_LIMIT = "rate_limit"        # 429 / quota — fallback immediately
    SERVER = "server"                # 5xx — fallback after brief retry
    TIMEOUT = "timeout"              # network timeout — fallback
    CONNECTION = "connection"        # DNS/connection refused — fallback
    AUTH = "auth"                    # invalid/expired key — skip provider
    BAD_RESPONSE = "bad_response"    # empty/invalid payload — fallback
    INVALID_REQUEST = "invalid_request"  # our prompt bug — do NOT fallback
    UNKNOWN = "unknown"              # conservative: fallback


class ProviderError(Exception):
    """A provider call failed; carries a normalised error kind."""

    def __init__(self, kind: ErrorKind, message: str,
                 retry_after: Optional[float] = None):
        super().__init__(message)
        self.kind = kind
        self.retry_after = retry_after


def _http_status(exc: BaseException) -> Optional[int]:
    """Best-effort HTTP status extraction from arbitrary SDK exceptions."""
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(status, bool) or not isinstance(status, int):
        status = None
    if status is None:
        response = getattr(exc, "response", None)
        if response is not None:
            resp_status = getattr(response, "status_code", None)
            if isinstance(resp_status, int):
                status = resp_status
    return status


def _retry_after_seconds(exc: BaseException) -> Optional[float]:
    """Respect Retry-After headers when the SDK exposes them (spec §21)."""
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    try:
        raw = headers.get("retry-after")
        if raw:
            return float(raw)
    except (TypeError, ValueError):
        pass
    return None


def _classify_status(status: Optional[int], kind_for_4xx: ErrorKind) -> ErrorKind:
    if status is None:
        return ErrorKind.UNKNOWN
    if status == 429:
        return ErrorKind.RATE_LIMIT
    if status >= 500:
        return ErrorKind.SERVER
    if status == 408:
        return ErrorKind.TIMEOUT
    if status in (401, 403):
        return ErrorKind.AUTH
    if 400 <= status < 500:
        return kind_for_4xx
    return ErrorKind.UNKNOWN


def classify_exception(exc: BaseException) -> ProviderError:
    """Map any SDK/network exception to a normalised ProviderError."""
    if isinstance(exc, ProviderError):
        return exc

    if isinstance(exc, asyncio.TimeoutError) or isinstance(
        exc, TimeoutError
    ):
        return ProviderError(ErrorKind.TIMEOUT, str(exc) or "timeout")

    message = str(exc).lower()
    status = _http_status(exc)

    if status is not None:
        kind = _classify_status(status, ErrorKind.INVALID_REQUEST)
        retry_after = _retry_after_seconds(exc)
        return ProviderError(
            kind, f"HTTP {status}: {exc}", retry_after=retry_after
        )

    # Textual fallbacks for SDKs that raise plain exceptions.
    if "quota" in message or "rate limit" in message or "resource_exhausted" in message:
        return ProviderError(ErrorKind.RATE_LIMIT, str(exc))
    if "api key" in message or "unauthorized" in message or "forbidden" in message \
            or "invalid_api_key" in message or "authentication" in message:
        return ProviderError(ErrorKind.AUTH, str(exc))
    if "timed out" in message or "timeout" in message:
        return ProviderError(ErrorKind.TIMEOUT, str(exc))
    if "connection" in message or "unreachable" in message or "unavailable" in message:
        return ProviderError(ErrorKind.CONNECTION, str(exc))
    if "429" in message:
        return ProviderError(ErrorKind.RATE_LIMIT, str(exc))
    return ProviderError(ErrorKind.UNKNOWN, str(exc))


class LLMProvider(ABC):
    """Common interface for chat-completion providers (spec §4)."""

    name: str = "base"

    def __init__(self, api_key: Optional[str], model: str,
                 timeout_seconds: float, max_output_tokens: int):
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_output_tokens = max_output_tokens

    @property
    def is_configured(self) -> bool:
        """A provider without a key is skipped, not failed (spec §24 LLM-7)."""
        return bool(self.api_key)

    @abstractmethod
    async def _generate(self, system_prompt: str, messages: list[dict],
                        temperature: float) -> str:
        """Provider-specific chat completion. Raises ProviderError on failure."""
        raise NotImplementedError

    async def generate(self, system_prompt: str, messages: list[dict],
                       temperature: float = 0.7) -> str:
        """Public entry point: timeout guard + error normalisation."""
        if not self.is_configured:
            raise ProviderError(ErrorKind.AUTH, f"{self.name}: no API key configured")
        try:
            text = await asyncio.wait_for(
                self._generate(system_prompt, messages, temperature),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise ProviderError(
                ErrorKind.TIMEOUT,
                f"{self.name}: timed out after {self.timeout_seconds:.0f}s",
            ) from exc
        except ProviderError:
            raise
        except Exception as exc:  # noqa: BLE001 — normalise SDK errors
            raise classify_exception(exc) from exc

        if not text or not text.strip():
            raise ProviderError(
                ErrorKind.BAD_RESPONSE, f"{self.name}: returned empty answer"
            )
        return text.strip()


# --------------------------------------------------------------------- #
# Gemini (LangChain ChatGoogleGenerativeAI — dependency already present)
# --------------------------------------------------------------------- #

class GeminiProvider(LLMProvider):
    """Google Gemini via the existing LangChain integration."""

    name = "gemini"

    async def _generate(self, system_prompt: str, messages: list[dict],
                        temperature: float) -> str:
        # Imported lazily so the module loads even without the dependency.
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=self.model,
            google_api_key=self.api_key,
            temperature=temperature,
            max_output_tokens=self.max_output_tokens,
            timeout=self.timeout_seconds,
            max_retries=0,  # retries/fallback handled by the LLMManager
        )
        lc_messages: list[Any] = [SystemMessage(content=system_prompt)]
        for msg in messages:
            if msg["role"] == "user":
                lc_messages.append(HumanMessage(content=msg["content"]))
            else:
                lc_messages.append(AIMessage(content=msg["content"]))

        response = await llm.ainvoke(lc_messages)
        content = response.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
                elif hasattr(block, "text") and isinstance(block.text, str):
                    parts.append(block.text)
            return "".join(parts)
        return str(content) if content is not None else ""


# --------------------------------------------------------------------- #
# Mistral AI (plain REST — no new heavy dependency needed)
# --------------------------------------------------------------------- #

class MistralProvider(LLMProvider):
    """Mistral AI chat completions via its OpenAI-compatible REST API."""

    name = "mistral"
    base_url = "https://api.mistral.ai/v1/chat/completions"

    async def _generate(self, system_prompt: str, messages: list[dict],
                        temperature: float) -> str:
        import httpx

        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": self.max_output_tokens,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.base_url, json=payload, headers=headers
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(ErrorKind.TIMEOUT, f"mistral: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ErrorKind.CONNECTION, f"mistral: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(
                _classify_status(response.status_code, ErrorKind.INVALID_REQUEST),
                f"mistral: HTTP {response.status_code}: {response.text[:200]}",
                retry_after=_retry_after_seconds(response),
            )

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(
                ErrorKind.BAD_RESPONSE, f"mistral: unexpected payload: {exc}"
            ) from exc


# --------------------------------------------------------------------- #
# Groq (OpenAI-compatible REST API)
# --------------------------------------------------------------------- #

class GroqProvider(LLMProvider):
    """Groq chat completions via its OpenAI-compatible REST API."""

    name = "groq"
    base_url = "https://api.groq.com/openai/v1/chat/completions"

    async def _generate(self, system_prompt: str, messages: list[dict],
                        temperature: float) -> str:
        import httpx

        payload = {
            "model": self.model,
            "temperature": temperature,
            "max_tokens": self.max_output_tokens,
            "messages": [{"role": "system", "content": system_prompt}, *messages],
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(
                    self.base_url, json=payload, headers=headers
                )
        except httpx.TimeoutException as exc:
            raise ProviderError(ErrorKind.TIMEOUT, f"groq: {exc}") from exc
        except httpx.HTTPError as exc:
            raise ProviderError(ErrorKind.CONNECTION, f"groq: {exc}") from exc

        if response.status_code != 200:
            raise ProviderError(
                _classify_status(response.status_code, ErrorKind.INVALID_REQUEST),
                f"groq: HTTP {response.status_code}: {response.text[:200]}",
                retry_after=_retry_after_seconds(response),
            )

        try:
            data = response.json()
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, ValueError) as exc:
            raise ProviderError(
                ErrorKind.BAD_RESPONSE, f"groq: unexpected payload: {exc}"
            ) from exc
