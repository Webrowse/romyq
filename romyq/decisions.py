"""Decision log — persistent record of governance events.

Records rule creation, rule removal, task rejections, planner overrides,
and operator interventions in .romyq/decisions.json.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone

_VERSION = 1
_MAX_ENTRIES = 1000

DECISION_TYPES = frozenset({
    "rule_added",
    "rule_removed",
    "task_rejected",
    "planner_override",
    "operator_intervention",
    "plan_repaired",
    "rule_triggered",
})


def _ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── persistence ───────────────────────────────────────────────────────────────

def load(decisions_path: str) -> list[dict]:
    """Load decisions.json. Returns [] on missing or corrupt file."""
    try:
        with open(decisions_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _write(decisions_path: str, entries: list[dict]) -> None:
    """Atomically write decisions.json."""
    dir_ = os.path.dirname(os.path.abspath(decisions_path))
    os.makedirs(dir_, exist_ok=True)
    if len(entries) > _MAX_ENTRIES:
        entries = entries[-_MAX_ENTRIES:]
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(entries, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, decisions_path)


# ── operations ────────────────────────────────────────────────────────────────

def record(
    decisions_path: str,
    type_: str,
    detail: str,
    **context,
) -> str:
    """Append a decision record. Returns the new decision ID. Never raises."""
    try:
        if type_ not in DECISION_TYPES:
            type_ = "planner_override"
        decision_id = uuid.uuid4().hex[:8]
        entry: dict = {
            "id": decision_id,
            "type": type_,
            "timestamp": _ts(),
            "detail": str(detail)[:300],
        }
        if context:
            entry["context"] = {k: v for k, v in context.items()}
        entries = load(decisions_path)
        entries.append(entry)
        _write(decisions_path, entries)
        return decision_id
    except Exception:
        return ""


def recent(decisions_path: str, limit: int = 20) -> list[dict]:
    """Return the most recent `limit` decisions, newest first."""
    entries = load(decisions_path)
    return list(reversed(entries[-limit:]))


def count(decisions_path: str) -> int:
    """Return total decision count."""
    return len(load(decisions_path))


def count_by_type(decisions_path: str) -> dict[str, int]:
    """Return {decision_type: count} over all decisions."""
    counts: dict[str, int] = {}
    for entry in load(decisions_path):
        t = entry.get("type", "unknown")
        counts[t] = counts.get(t, 0) + 1
    return counts


def format_decisions(decisions_path: str, limit: int = 20) -> str:
    """Return a human-readable decisions listing for CLI display."""
    entries = recent(decisions_path, limit=limit)
    if not entries:
        return "(no decisions recorded)"
    lines = []
    for d in entries:
        ts = d.get("timestamp", "")[:19].replace("T", " ")
        type_ = d.get("type", "?")
        detail = d.get("detail", "")[:80]
        lines.append(f"  [{ts}] {type_}: {detail}")
    return "\n".join(lines)
