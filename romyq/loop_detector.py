"""Planner loop detection — identify cycling and oscillation patterns.

Works on a sequence of task fingerprints (no task text needed).
All detection is stateless; call detect() with the recent history.
"""
from __future__ import annotations

from typing import NamedTuple


class LoopPattern(NamedTuple):
    pattern_type: str   # "straight" | "oscillation"
    fingerprints: list  # participating fingerprint(s)
    count: int          # how many iterations observed
    description: str    # human-readable summary


def detect(
    fps: list[str],
    straight_threshold: int = 3,
    oscillation_min: int = 4,
) -> list[LoopPattern]:
    """Detect cycling patterns in a sequence of task fingerprints.

    fps         — ordered list (oldest → most recent).
    straight_threshold — how many consecutive identical FPs to flag.
    oscillation_min    — minimum run length to flag an A-B-A-B cycle.

    Returns a (possibly empty) list of detected LoopPattern instances.
    """
    patterns: list[LoopPattern] = []

    if not fps:
        return patterns

    # ── Straight loop: same FP repeated N times at the tail ──────────────────
    if len(fps) >= straight_threshold:
        last = fps[-1]
        streak = 1
        for fp in reversed(fps[:-1]):
            if fp == last:
                streak += 1
            else:
                break
        if streak >= straight_threshold:
            patterns.append(LoopPattern(
                pattern_type="straight",
                fingerprints=[last],
                count=streak,
                description=(
                    f"Same task repeated {streak} consecutive times "
                    f"(fingerprint: {last})"
                ),
            ))

    # ── Oscillation: A-B-A-B-A across the tail ───────────────────────────────
    if len(fps) >= oscillation_min:
        window = fps[-oscillation_min:]
        unique = set(window)
        if len(unique) == 2:
            # Every adjacent pair must differ (strict alternation)
            is_alt = all(window[i] != window[i + 1] for i in range(len(window) - 1))
            if is_alt:
                a, b = sorted(unique)
                patterns.append(LoopPattern(
                    pattern_type="oscillation",
                    fingerprints=[a, b],
                    count=oscillation_min,
                    description=(
                        f"Planner oscillating between 2 tasks over last "
                        f"{oscillation_min} iterations "
                        f"(fingerprints: {a}, {b})"
                    ),
                ))

    return patterns


def describe(patterns: list[LoopPattern]) -> str:
    """Return a compact text description of detected patterns (empty = healthy)."""
    if not patterns:
        return ""
    return "\n".join(f"  [{p.pattern_type}] {p.description}" for p in patterns)
