import json
import os
import tempfile
from datetime import datetime, timezone


DEFAULT_STATE = {
    "tasks_completed": 0,
    "last_audit": 0,
    "status": "running",
    "heartbeat": "",
    "current_task": "",
    "last_commit": "",
    "audit_interval": 5,
    # Rate-limit fields (populated while Claude is throttled)
    "resume_at": "",        # ISO timestamp when the rate limit lifts
    "provider": "",         # "claude" when throttled by Claude
    # Control flags (written by romyq pause / resume / stop)
    "paused": False,        # loop waits between tasks when True
    "stop_requested": False,  # loop exits gracefully when True
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


def heartbeat(data: dict) -> None:
    data["heartbeat"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )


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


def audit_due(data: dict) -> bool:
    return (data["tasks_completed"] - data["last_audit"]) >= data["audit_interval"]


def next_mode(data: dict) -> str:
    return "audit" if audit_due(data) else "implementation"
