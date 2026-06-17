import json
from datetime import datetime, timezone


HISTORY_FILE = "task_history.json"


def _load(path: str = HISTORY_FILE) -> list:
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(history: list, path: str = HISTORY_FILE) -> None:
    with open(path, "w") as f:
        json.dump(history, f, indent=2)


def add_entry(
    task: str,
    mode: str,
    success: bool,
    commit: str,
    validation_reason: str,
    path: str = HISTORY_FILE,
) -> None:
    history = _load(path)
    history.append(
        {
            "timestamp": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "task": task,
            "mode": mode,
            "success": success,
            "commit": commit,
            "validation_reason": validation_reason,
        }
    )
    _save(history, path)


def recent(limit: int = 20, path: str = HISTORY_FILE) -> list:
    return _load(path)[-limit:]


def recent_text(limit: int = 20, path: str = HISTORY_FILE) -> str:
    tasks = recent(limit=limit, path=path)

    if not tasks:
        return "No previous tasks."

    lines = []
    for item in tasks:
        lines.append(
            f"Task:\n{item['task']}\n\n"
            f"Mode: {item['mode']}\n"
            f"Success: {item['success']}\n"
            f"Commit: {item['commit']}"
        )

    return "\n\n---\n\n".join(lines)
