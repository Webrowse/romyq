import json
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

STATE_FILE = "state.json"


def load(path: str = STATE_FILE) -> dict:
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
        backup = DEFAULT_STATE.copy()
        save(backup, path)
        return backup


def save(data: dict, path: str = STATE_FILE) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


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
