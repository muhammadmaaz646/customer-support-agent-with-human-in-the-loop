"""
Minimal retrieval over the policy knowledge base.

Keyword-overlap scoring, not embeddings — deliberately dependency-free so
the whole agent runs with zero setup. Swap in real embeddings (or reuse
your project-4 RAG bot) as a drop-in replacement for `retrieve()`; nothing
else in the agent needs to know the difference.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path

KB_DIR = Path(__file__).parent / "policy_kb"

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of",
    "and", "or", "for", "on", "in", "at", "my", "i", "it", "this", "that",
    "do", "does", "can", "you", "your", "what", "how", "if", "will", "with",
}


@dataclass
class Chunk:
    source: str
    text: str


def _stem(word: str) -> str:
    """Very light suffix stripping so 'return'/'returned'/'returns' overlap."""
    for suffix in ("ing", "edly", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-z']+", text.lower())
    return {_stem(w) for w in words if w not in STOPWORDS and len(w) > 2}


def _load_chunks() -> list[Chunk]:
    chunks = []
    for path in sorted(KB_DIR.glob("*.md")):
        # split on blank lines -> paragraph-level chunks
        paragraphs = [p.strip() for p in path.read_text().split("\n\n") if p.strip()]
        for p in paragraphs:
            if p.startswith("# "):
                continue  # skip bare titles
            chunks.append(Chunk(source=path.name, text=p))
    return chunks


_CHUNKS = _load_chunks()  # loaded once at import


def retrieve(query: str, top_k: int = 2) -> list[Chunk]:
    query_words = _tokenize(query)
    if not query_words:
        return []

    scored = []
    for chunk in _CHUNKS:
        chunk_words = _tokenize(chunk.text)
        overlap = len(query_words & chunk_words)
        if overlap > 0:
            scored.append((overlap, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [c for _, c in scored[:top_k]]
