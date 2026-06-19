from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

from .runstate import RunState, is_valid_transition


DEFAULT_STATE = {
    # ── progress ──────────────────────────────────────────────────────────────
    "tasks_completed": 0,
    "last_audit": 0,
    "audit_interval": 5,

    # ── runtime ───────────────────────────────────────────────────────────────
    "status": "running",      # coarse status shown by UI (running/stopped/completed/rate_limited)
    "phase": "idle",          # fine-grained RunState (idle/planning/executing/validating/…)
    "heartbeat": "",          # ISO timestamp, updated throughout the loop
    "current_task": "",

    # ── git ───────────────────────────────────────────────────────────────────
    "last_commit": "",

    # ── rate-limit (populated while Claude is throttled) ──────────────────────
    "resume_at": "",          # ISO timestamp when the rate limit lifts
    "provider": "",           # "claude" when throttled

    # ── control flags (written by romyq pause / resume / stop) ───────────────
    "paused": False,
    "stop_requested": False,

    # ── persistent failure tracking ───────────────────────────────────────────
    "current_task_key": "",           # MD5[:12] of the task in progress
    "current_task_attempts": 0,       # how many times it has been tried
    "last_failure_reason": "",        # why the last attempt failed
    "last_failure_timestamp": "",     # ISO timestamp of the last failure
    "consecutive_failures": 0,        # consecutive failures across all tasks
    "max_task_attempts": 3,           # ceiling before a task is marked BLOCKED

    # ── last validation ───────────────────────────────────────────────────────
    "last_validation_evidence": [],   # list[str] from the most recent validate()
}


def load(path: str) -> dict:
    try:
        with open(path) as f:
            data = json.load(f)

        for key, value in DEFAULT_STATE.items():
            if key not in data:
                data[key] = value

        return data

    except FileNotFoundError:
        save(DEFAULT_STATE, path)
        return DEFAULT_STATE.copy()

    except json.JSONDecodeError:
        print(f"[romyq] Warning: {path} was corrupted — resetting to defaults.", flush=True)
        backup = DEFAULT_STATE.copy()
        save(backup, path)
        return backup


def save(data: dict, path: str) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as f:
        json.dump(data, f, indent=2)
        tmp = f.name
    os.replace(tmp, path)


# ── heartbeat and phase ───────────────────────────────────────────────────────

def heartbeat(data: dict) -> None:
    data["heartbeat"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def set_phase(data: dict, phase: str | RunState) -> None:
    """Transition to a new RunState phase, logging invalid transitions."""
    new_value = phase.value if isinstance(phase, RunState) else phase
    current = data.get("phase", "idle")
    if not is_valid_transition(current, new_value):
        print(
            f"[romyq] Warning: unexpected phase transition {current!r} → {new_value!r}",
            file=sys.stderr, flush=True,
        )
    data["phase"] = new_value
    heartbeat(data)


# ── task management ───────────────────────────────────────────────────────────

def set_current_task(data: dict, task: str) -> None:
    data["current_task"] = task


def increment_tasks(data: dict) -> None:
    data["tasks_completed"] += 1


def mark_audit_complete(data: dict) -> None:
    data["last_audit"] = data["tasks_completed"]


def set_last_commit(data: dict, commit: str) -> None:
    data["last_commit"] = commit


def mark_completed(data: dict) -> None:
    data["status"] = "completed"


# ── rate-limit helpers ────────────────────────────────────────────────────────

def set_rate_limited(data: dict, resume_at: str, provider: str = "claude") -> None:
    data["status"] = "rate_limited"
    data["resume_at"] = resume_at
    data["provider"] = provider


def clear_rate_limit(data: dict) -> None:
    data["status"] = "running"
    data["resume_at"] = ""
    data["provider"] = ""


def mark_stopped(data: dict) -> None:
    data["status"] = "stopped"
    data["stop_requested"] = False


# ── persistent failure tracking ───────────────────────────────────────────────

def record_task_failure(data: dict, task_key: str, reason: str) -> None:
    """Update persistent counters after a task failure.

    Increments current_task_attempts when the key matches the in-progress task.
    Resets the per-task counter when a new task key appears (different task).
    Always increments consecutive_failures.
    """
    if data.get("current_task_key") == task_key:
        data["current_task_attempts"] = data.get("current_task_attempts", 0) + 1
    else:
        data["current_task_key"] = task_key
        data["current_task_attempts"] = 1
    data["last_failure_reason"] = reason
    data["last_failure_timestamp"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    data["consecutive_failures"] = data.get("consecutive_failures", 0) + 1


def record_task_success(data: dict) -> None:
    """Reset per-task and consecutive failure counters on success."""
    data["current_task_key"] = ""
    data["current_task_attempts"] = 0
    data["last_failure_reason"] = ""
    data["consecutive_failures"] = 0


def is_task_blocked(data: dict, task_key: str) -> bool:
    """True when the current task has hit max_task_attempts.

    This persists across restarts because the key and attempt count are
    stored in state.json.
    """
    if data.get("current_task_key") != task_key:
        return False
    ceiling = data.get("max_task_attempts", DEFAULT_STATE["max_task_attempts"])
    return data.get("current_task_attempts", 0) >= ceiling


# ── control-flag race mitigation ──────────────────────────────────────────────

def refresh_control_flags(data: dict, path: str) -> None:
    """Merge stop_requested and paused from disk into the in-memory dict.

    Call this immediately before save() whenever the loop has held the dict
    across a long-running operation (Claude execution, rate-limit sleep).
    Without this, any CLI write to those flags during that window would be
    silently overwritten by the loop's save.
    """
    try:
        with open(path) as f:
            on_disk = json.load(f)
        for flag in ("paused", "stop_requested"):
            if flag in on_disk:
                data[flag] = on_disk[flag]
    except Exception:
        pass


# ── audit scheduling ──────────────────────────────────────────────────────────

def audit_due(data: dict) -> bool:
    return (data["tasks_completed"] - data["last_audit"]) >= data["audit_interval"]


def next_mode(data: dict) -> str:
    return "audit" if audit_due(data) else "implementation"
