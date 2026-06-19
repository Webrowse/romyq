"""Execution memory — persistent per-task outcome history across all loop runs.

Persisted in .romyq/memory.json.

Format:
  {
    "version": 1,
    "entries": [<MemoryEntry>, ...],        # ordered oldest→newest
    "missions": { <mission_fp>: <MissionRecord>, ... }
  }

Bounded to MAX_ENTRIES (default 2 000) — oldest entries pruned on record().
All writes are atomic (tmp + fsync + os.replace).
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import TypedDict

from .fingerprint import fingerprint as _fp, is_similar, normalize, similarity

_DEFAULT_MAX = 2_000
_VERSION = 1


# ── data structures ───────────────────────────────────────────────────────────

class MemoryEntry(TypedDict):
    fp:      str         # task fingerprint (12-char SHA-1 of normalized text)
    task:    str         # original task text (first 400 chars)
    norm:    str         # normalized task text
    mfp:     str         # mission fingerprint
    out:     str         # SUCCESS | FAILURE | NO_ACTION_REQUIRED
    ev:      list[str]   # validator evidence (capped at 5 lines)
    why:     str         # failure reason
    n:       int         # retry count at time of this entry
    done:    bool        # True = completed successfully
    ts:      str         # ISO-8601 UTC timestamp


class MissionRecord(TypedDict):
    preview:    str
    total:      int
    ok:         int
    blocked:    int
    first_seen: str
    last_seen:  str


def _empty() -> dict:
    return {"version": _VERSION, "entries": [], "missions": {}}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── I/O ───────────────────────────────────────────────────────────────────────

def load(path: str) -> dict:
    """Load memory.json; return a clean default structure on any error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or "entries" not in data:
            return _empty()
        # Forward-compat: ensure both top-level keys exist
        data.setdefault("missions", {})
        data.setdefault("version", _VERSION)
        return data
    except FileNotFoundError:
        return _empty()
    except (json.JSONDecodeError, ValueError):
        return _empty()


def _save(data: dict, path: str) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, path)


def _max_entries() -> int:
    try:
        return int(os.getenv("ROMYQ_MAX_MEMORY", str(_DEFAULT_MAX)))
    except (TypeError, ValueError):
        return _DEFAULT_MAX


# ── write API ─────────────────────────────────────────────────────────────────

def record(
    path: str,
    task: str,
    mission_fp: str,
    outcome: str,
    evidence: list[str],
    failure_reason: str,
    retry_count: int,
) -> MemoryEntry:
    """Append a task execution outcome to memory.json.

    Prunes oldest entries if the log exceeds ROMYQ_MAX_MEMORY.
    """
    data = load(path)
    fp = _fp(task)
    entry: MemoryEntry = {
        "fp":   fp,
        "task": task[:400],
        "norm": normalize(task)[:400],
        "mfp":  mission_fp,
        "out":  outcome,
        "ev":   evidence[:5],
        "why":  failure_reason[:300],
        "n":    retry_count,
        "done": outcome != "FAILURE",
        "ts":   _now(),
    }
    data["entries"].append(entry)

    cap = _max_entries()
    if len(data["entries"]) > cap:
        data["entries"] = data["entries"][-cap:]

    _save(data, path)
    return entry


def update_mission(
    path: str,
    mission_fp: str,
    preview: str,
    completed: bool,
    blocked: bool,
) -> None:
    """Update mission-level aggregate counters."""
    data = load(path)
    rec = data["missions"].get(mission_fp, {
        "preview": preview[:120],
        "total": 0,
        "ok": 0,
        "blocked": 0,
        "first_seen": _now(),
        "last_seen": _now(),
    })
    rec["total"] += 1
    if completed:
        rec["ok"] += 1
    if blocked:
        rec["blocked"] += 1
    rec["last_seen"] = _now()
    rec["preview"] = preview[:120]
    data["missions"][mission_fp] = rec
    _save(data, path)


# ── query API ─────────────────────────────────────────────────────────────────

def entries_for(path: str, fp: str) -> list[MemoryEntry]:
    """Return all entries whose fingerprint matches fp (exact match)."""
    data = load(path)
    return [e for e in data["entries"] if e.get("fp") == fp]


def entries_similar_to(path: str, task: str, threshold: float = 0.4) -> list[MemoryEntry]:
    """Return entries that are similar to task (exact fp OR Jaccard ≥ threshold)."""
    target_fp = _fp(task)
    data = load(path)
    results: list[MemoryEntry] = []
    for e in data["entries"]:
        if e.get("fp") == target_fp:
            results.append(e)
        elif similarity(task, e.get("norm", e.get("task", ""))) >= threshold:
            results.append(e)
    return results


def recent_failures(path: str, limit: int = 20) -> list[MemoryEntry]:
    """Return the most recent failure entries."""
    data = load(path)
    failures = [e for e in data["entries"] if e.get("out") == "FAILURE"]
    return failures[-limit:]


def most_failed(path: str, limit: int = 10) -> list[tuple[str, int, str, str]]:
    """Return top-N (fp, failure_count, task_preview, last_reason) tuples."""
    data = load(path)
    counts: dict[str, int] = {}
    previews: dict[str, str] = {}
    reasons: dict[str, str] = {}
    for e in data["entries"]:
        if e.get("out") == "FAILURE":
            fp = e["fp"]
            counts[fp] = counts.get(fp, 0) + 1
            previews[fp] = e.get("task", "")[:80]
            reasons[fp] = e.get("why", "")
    ranked = sorted(counts.items(), key=lambda x: -x[1])[:limit]
    return [(fp, cnt, previews[fp], reasons[fp]) for fp, cnt in ranked]


def failure_count(path: str, fp: str) -> int:
    """Return the number of times a task fingerprint has failed."""
    data = load(path)
    return sum(1 for e in data["entries"] if e.get("fp") == fp and e.get("out") == "FAILURE")


def prior_outcomes_text(path: str, task: str, mission_fp: str = "") -> str:
    """Human-readable summary of prior outcomes for a task (for injection into prompts).

    Returns '' when no prior outcomes exist.
    """
    entries = entries_similar_to(path, task)
    if not entries:
        return ""

    failures = [e for e in entries if e.get("out") == "FAILURE"]
    successes = [e for e in entries if e.get("out") != "FAILURE"]

    lines: list[str] = []
    if failures:
        lines.append(
            f"[Memory] This task has failed {len(failures)} time(s) in execution memory."
        )
        lines.append("Previous failures:")
        for i, e in enumerate(failures[-5:], 1):
            ts = e.get("ts", "")[:10]
            why = e.get("why", "unknown")[:120]
            ev = ", ".join(e.get("ev", [])[:3])
            lines.append(f"  {i}. [{ts}] Reason: {why}")
            if ev:
                lines.append(f"     Evidence: {ev}")
        lines.append("Do NOT repeat the same approach. The validator will fail again.")

    if successes:
        lines.append(
            f"[Memory] This task also succeeded {len(successes)} time(s) — "
            "check recent commits to see what worked."
        )

    return "\n".join(lines) if lines else ""


def overall_success_rate(path: str) -> float:
    """Overall success rate from memory (0.0–1.0, or -1.0 if empty)."""
    data = load(path)
    entries = data["entries"]
    if not entries:
        return -1.0
    successes = sum(1 for e in entries if e.get("out") != "FAILURE")
    return round(successes / len(entries), 4)


def retry_rate(path: str) -> float:
    """Fraction of unique task fingerprints that were retried at least once."""
    data = load(path)
    entries = data["entries"]
    if not entries:
        return 0.0
    fp_counts: dict[str, int] = {}
    for e in entries:
        fp = e["fp"]
        fp_counts[fp] = fp_counts.get(fp, 0) + 1
    retried = sum(1 for c in fp_counts.values() if c > 1)
    return round(retried / len(fp_counts), 4) if fp_counts else 0.0


def avg_attempts_per_task(path: str) -> float:
    """Average number of execution attempts per unique task fingerprint."""
    data = load(path)
    entries = data["entries"]
    if not entries:
        return 0.0
    fp_counts: dict[str, int] = {}
    for e in entries:
        fp_counts[e["fp"]] = fp_counts.get(e["fp"], 0) + 1
    if not fp_counts:
        return 0.0
    return round(sum(fp_counts.values()) / len(fp_counts), 2)


def recent_fingerprints(path: str, limit: int = 30) -> list[str]:
    """Return the most recent task fingerprints (oldest first)."""
    data = load(path)
    entries = data["entries"][-limit:]
    return [e["fp"] for e in entries]


def mission_summary(path: str, mission_fp: str) -> MissionRecord | None:
    data = load(path)
    return data["missions"].get(mission_fp)


def all_missions(path: str) -> dict[str, MissionRecord]:
    return load(path).get("missions", {})
