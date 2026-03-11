"""BM25 passage retriever for consistency checking.

Uses jieba segmentation + rank_bm25 for keyword-based retrieval.
No LLM needed -- runs entirely locally.
"""

from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger("novel")

# Lazy imports for optional dependencies
_jieba = None
_BM25Okapi = None


def _ensure_deps() -> bool:
    """Lazily import jieba and rank_bm25. Returns True if available."""
    global _jieba, _BM25Okapi  # noqa: PLW0603
    if _jieba is not None and _BM25Okapi is not None:
        return True
    try:
        import jieba  # type: ignore[import-untyped]
        from rank_bm25 import BM25Okapi  # type: ignore[import-untyped]

        _jieba = jieba
        _BM25Okapi = BM25Okapi
        return True
    except ImportError:
        log.debug("jieba or rank_bm25 not installed -- BM25Retriever disabled")
        return False


_PARA_SPLIT_RE = re.compile(r"\n\s*\n|\n")


class BM25Retriever:
    """BM25-based passage retriever for Chinese text.

    Segments text with jieba, indexes paragraphs with BM25Okapi,
    and supports keyword queries for consistency checking.
    """

    def __init__(self) -> None:
        self._available = _ensure_deps()
        # Each entry: (chapter_number, paragraph_text, tokenized_paragraph)
        self._docs: list[tuple[int, str]] = []
        self._tokenized: list[list[str]] = []
        self._bm25: Any | None = None

    # ------------------------------------------------------------------
    # Index building
    # ------------------------------------------------------------------

    def add_chapter(self, chapter_number: int, text: str) -> None:
        """Segment *text* into paragraphs, tokenize with jieba, add to index.

        Args:
            chapter_number: The chapter this text belongs to.
            text: Raw chapter text.
        """
        if not text or not text.strip():
            return
        if not self._available:
            return

        paragraphs = [p.strip() for p in _PARA_SPLIT_RE.split(text) if p.strip()]
        for para in paragraphs:
            tokens = _jieba.lcut(para)  # type: ignore[union-attr]
            self._docs.append((chapter_number, para))
            self._tokenized.append(tokens)

        # Rebuild BM25 index (fast for typical novel sizes)
        self._bm25 = _BM25Okapi(self._tokenized)  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query(self, query_text: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Return the *top_k* most relevant passages for *query_text*.

        Returns:
            List of ``{"chapter": int, "text": str, "score": float}``
            sorted by descending BM25 score.  Empty list when the
            corpus is empty or dependencies are unavailable.
        """
        if not self._available or not self._docs or self._bm25 is None:
            return []
        if not query_text or not query_text.strip():
            return []

        tokens = _jieba.lcut(query_text)  # type: ignore[union-attr]
        scores = self._bm25.get_scores(tokens)

        # Pair each doc with its score, sort descending
        indexed = sorted(enumerate(scores), key=lambda x: x[1], reverse=True)

        results: list[dict[str, Any]] = []
        for idx, score in indexed[:top_k]:
            if score <= 0:
                break
            chapter_number, para_text = self._docs[idx]
            results.append(
                {
                    "chapter": chapter_number,
                    "text": para_text,
                    "score": float(score),
                }
            )
        return results

    def query_by_entity(self, entity_name: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Shortcut to find paragraphs mentioning a specific entity name.

        This is a thin wrapper around :meth:`query` -- the entity name is
        used directly as the query string so BM25 will rank paragraphs
        containing that name higher.
        """
        return self.query(entity_name, top_k=top_k)
