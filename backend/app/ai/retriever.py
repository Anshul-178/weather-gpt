"""RAG retriever (optional module).

RAG supplements the LLM with reference information (weather terminology,
safety guidance, activity thresholds). It NEVER replaces live weather data:
current conditions and forecasts always come from the weather provider.

The vector store is behind a factory so Chroma can be swapped later without
touching calling code. When Chroma/dependencies are unavailable the
retriever degrades to a small built-in knowledge base.
"""

from typing import Optional, Protocol

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


class Retriever(Protocol):
    """Retriever interface — swap implementations freely."""

    async def retrieve(self, query: str, top_k: int | None = None) -> str:
        """Return reference text relevant to the query (may be empty)."""
        ...


# --------------------------------------------------------------------- #
# Built-in fallback knowledge base (deterministic, no external deps)
# --------------------------------------------------------------------- #

_KNOWLEDGE: list[tuple[str, str]] = [
    (
        "wind cycling safety",
        "Wind guidance for cycling: below 20 km/h is comfortable; 20-35 km/h "
        "makes riding noticeably harder, especially with gusts and on open "
        "roads; above 40 km/h cycling becomes difficult and potentially "
        "unsafe for most riders.",
    ),
    (
        "heat safety",
        "Heat guidance: above 35°C feels-like temperature, avoid strenuous "
        "outdoor activity during midday, hydrate frequently, and prefer early "
        "morning or evening. Heatstroke risk rises with high humidity.",
    ),
    (
        "uv index meaning",
        "UV index scale: 0-2 low (no protection needed), 3-7 moderate to high "
        "(sunscreen, sunglasses), 8-10 very high (avoid midday sun), 11+ "
        "extreme (full protection advised).",
    ),
    (
        "rain probability meaning",
        "Precipitation probability is the chance that measurable rain falls "
        "somewhere in the forecast area during the period. 0-20% unlikely, "
        "30-50% possible, 60-80% likely, above 80% very likely.",
    ),
    (
        "visibility driving",
        "Visibility guidance for driving: below 1 km is hazardous (fog/heavy "
        "rain); 1-4 km requires reduced speed and headlights; above 10 km is "
        "considered clear.",
    ),
    (
        "thunderstorm safety",
        "Thunderstorm guidance: seek sturdy shelter, avoid open fields, tall "
        "isolated trees and water. Wait 30 minutes after the last thunder "
        "before resuming outdoor activity.",
    ),
]

_DEFAULT_TOP_K = 3


class KeywordRetriever:
    """Tiny deterministic retriever over the built-in knowledge base."""

    async def retrieve(self, query: str, top_k: int | None = None) -> str:
        """Return concatenated knowledge entries matching query keywords."""
        top_k = top_k or _DEFAULT_TOP_K
        words = {w for w in query.lower().split() if len(w) > 3}
        scored: list[tuple[int, str]] = []
        for key, text in _KNOWLEDGE:
            score = sum(1 for w in key.split() if w in query.lower())
            score += sum(1 for w in words if w in text.lower())
            if score > 0:
                scored.append((score, text))
        scored.sort(key=lambda pair: -pair[0])
        return "\n\n".join(text for _, text in scored[:top_k])


class ChromaRetriever:
    """Chroma-backed retriever (optional dependency, enabled via settings)."""

    def __init__(self) -> None:
        self._collection = None

    def _get_collection(self):
        if self._collection is not None:
            return self._collection
        try:
            import chromadb  # type: ignore

            client = chromadb.PersistentClient(path=settings.chroma_dir)
            self._collection = client.get_or_create_collection("weathergpt_docs")
            return self._collection
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chroma unavailable, falling back: %s", exc)
            return None

    async def add_documents(self, documents: list[str], metadatas: list[dict] | None = None) -> int:
        """Add documents to the vector store with simple chunking."""
        collection = self._get_collection()
        if collection is None or not documents:
            return 0
        chunks: list[str] = []
        for doc in documents:
            start = 0
            while start < len(doc):
                chunks.append(doc[start : start + settings.rag_chunk_size])
                start += settings.rag_chunk_size - settings.rag_chunk_overlap
        ids = [f"doc-{abs(hash(c)) % 10**10}" for c in chunks]
        collection.upsert(documents=chunks, ids=ids, metadatas=metadatas)
        return len(chunks)

    async def retrieve(self, query: str, top_k: int | None = None) -> str:
        """Retrieve similar chunks from Chroma; empty string on failure."""
        top_k = top_k or settings.rag_top_k
        collection = self._get_collection()
        if collection is None:
            return await KeywordRetriever().retrieve(query, top_k)
        try:
            result = collection.query(query_texts=[query], n_results=top_k)
            docs = (result.get("documents") or [[]])[0]
            return "\n\n".join(docs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Chroma retrieval failed: %s", exc)
            return ""


def get_retriever() -> Retriever:
    """Return the configured retriever implementation."""
    if settings.rag_enabled:
        return ChromaRetriever()
    return KeywordRetriever()


async def maybe_retrieve(query: str, enabled: bool) -> Optional[str]:
    """Retrieve RAG context when enabled; returns None when disabled/empty."""
    if not enabled:
        return None
    try:
        return await get_retriever().retrieve(query)
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG retrieval failed (non-fatal): %s", exc)
        return None
