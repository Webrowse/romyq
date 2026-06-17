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


def audit_due(data: dict) -> bool:
    return (data["tasks_completed"] - data["last_audit"]) >= data["audit_interval"]


def next_mode(data: dict) -> str:
    return "audit" if audit_due(data) else "implementation"
