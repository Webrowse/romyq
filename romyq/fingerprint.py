"""Stable task identity via text normalization and content fingerprinting.

Provides:
  normalize()    — canonical form for stable comparison
  fingerprint()  — 12-char SHA-1 of normalized text
  similarity()   — Jaccard overlap of meaningful tokens (0.0–1.0)
  is_similar()   — shortcut threshold check

No external dependencies; no ML models required.
"""
from __future__ import annotations

import hashlib
import re

# High-frequency filler words that carry no task-specific meaning.
_FILLER: frozenset[str] = frozenset({
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "are", "was", "were", "be", "been",
    "it", "its", "this", "that", "these", "those", "then", "than",
    "we", "you", "i", "me", "my", "our", "their", "also", "just", "up",
})


def normalize(text: str) -> str:
    """Return the canonical form of a task string.

    Lowercases, collapses whitespace, and strips punctuation that does not
    carry semantic weight (keeps alphanumerics, spaces, hyphens, and slashes
    so that paths like /health are preserved).
    """
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'[^\w\s/\-]', '', text)
    return text


def fingerprint(text: str) -> str:
    """Return a 12-character deterministic fingerprint of the task text."""
    return hashlib.sha1(normalize(text).encode('utf-8')).hexdigest()[:12]


def _tokens(text: str) -> frozenset[str]:
    """Return meaningful word tokens, stripping filler and very short words."""
    return frozenset(
        w for w in normalize(text).split()
        if w not in _FILLER and len(w) > 1
    )


def similarity(a: str, b: str) -> float:
    """Jaccard similarity (0.0–1.0) between two task texts based on word overlap.

    Scores above 0.4 indicate the tasks share enough vocabulary to be
    considered related.  Exact fingerprint matches always score 1.0.
    """
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_similar(a: str, b: str, threshold: float = 0.4) -> bool:
    """True when tasks share a fingerprint or sufficient word overlap."""
    if fingerprint(a) == fingerprint(b):
        return True
    return similarity(a, b) >= threshold
