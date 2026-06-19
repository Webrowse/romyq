"""Append-only event log for Romyq postmortem debugging.

Events are written as newline-delimited JSON (NDJSON) to .romyq/events.log.
The log is append-only and survives restarts.  emit() never raises so it
cannot break the main loop.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any

# ── event type constants ──────────────────────────────────────────────────────

LOOP_STARTED = "loop_started"
LOOP_STOPPED = "loop_stopped"
TASK_STARTED = "task_started"
TASK_COMPLETED = "task_completed"
TASK_BLOCKED = "task_blocked"
VALIDATOR_PASSED = "validator_passed"
VALIDATOR_FAILED = "validator_failed"
NO_ACTION_REQUIRED = "no_action_required"
RETRY = "retry"
PAUSE_DETECTED = "pause_detected"
RESUME_DETECTED = "resume_detected"
STOP_DETECTED = "stop_detected"
RATE_LIMIT_DETECTED = "rate_limit_detected"
RATE_LIMIT_RECOVERED = "rate_limit_recovered"
CRASH_RECOVERED = "crash_recovered"
PHASE_CHANGED = "phase_changed"
CLAUDE_CANCELLED = "claude_cancelled"
CONTEXT_REFRESHED = "context_refreshed"
KNOWLEDGE_REFRESHED = "knowledge_refreshed"
OPERATOR_INSTRUCTION = "operator_instruction"
TASK_APPROVED = "task_approved"
TASK_REJECTED = "task_rejected"
GUARDRAIL_TRIGGERED = "guardrail_triggered"


# ── core operations ───────────────────────────────────────────────────────────

def emit(path: str, event_type: str, **kwargs: Any) -> None:
    """Append a single structured event to the log.  Never raises."""
    try:
        entry: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "event": event_type,
        }
        entry.update(kwargs)
        line = json.dumps(entry, separators=(",", ":")) + "\n"
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def tail(path: str, n: int = 50) -> list[dict]:
    """Return the last n events from the log.  Returns [] if log is absent."""
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
        result: list[dict] = []
        for raw in lines[-n:]:
            raw = raw.strip()
            if raw:
                try:
                    result.append(json.loads(raw))
                except json.JSONDecodeError:
                    pass
        return result
    except FileNotFoundError:
        return []


def prune(path: str, max_entries: int = 10_000) -> int:
    """Remove oldest events so the log holds at most max_entries lines.

    Uses an atomic tmp-file write so the log is never left partially written.
    Returns the number of lines removed.  Returns 0 if the file is absent or
    already within the limit.  Never raises.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        if len(lines) <= max_entries:
            return 0
        to_keep = lines[-max_entries:]
        removed = len(lines) - len(to_keep)
        dir_ = os.path.dirname(os.path.abspath(path))
        with tempfile.NamedTemporaryFile(
            "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
        ) as f:
            f.writelines(to_keep)
            f.flush()
            os.fsync(f.fileno())
            tmp = f.name
        os.replace(tmp, path)
        return removed
    except FileNotFoundError:
        return 0
    except Exception:
        return 0


def count_by_type(path: str) -> dict[str, int]:
    """Return a {event_type: count} summary over the whole log."""
    counts: dict[str, int] = {}
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    t = entry.get("event", "unknown")
                    counts[t] = counts.get(t, 0) + 1
                except json.JSONDecodeError:
                    pass
    except FileNotFoundError:
        pass
    return counts
