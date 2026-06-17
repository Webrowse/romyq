import json
from datetime import datetime, timezone


DEFAULT_HISTORY_FILE = "task_history.json"


def load_history(
    path: str = DEFAULT_HISTORY_FILE,
) -> list:
    try:
        with open(path) as f:
            return json.load(f)

    except FileNotFoundError:
        return []

    except json.JSONDecodeError:
        return []


def save_history(
    history: list,
    path: str = DEFAULT_HISTORY_FILE,
) -> None:
    with open(path, "w") as f:
        json.dump(
            history,
            f,
            indent=2,
        )


def add_entry(
    task: str,
    mode: str,
    success: bool,
    commit: str,
    validation_reason: str,
    path: str = DEFAULT_HISTORY_FILE,
) -> None:
    history = load_history(path)

    history.append(
        {
            "timestamp": (
                datetime.now(timezone.utc)
                .replace(microsecond=0)
                .isoformat()
            ),
            "task": task,
            "mode": mode,
            "success": success,
            "commit": commit,
            "validation_reason": validation_reason,
        }
    )

    save_history(
        history,
        path,
    )


def recent_tasks(
    limit: int = 20,
    path: str = DEFAULT_HISTORY_FILE,
) -> list:
    history = load_history(path)

    return history[-limit:]


def recent_tasks_text(
    limit: int = 20,
    path: str = DEFAULT_HISTORY_FILE,
) -> str:
    tasks = recent_tasks(
        limit=limit,
        path=path,
    )

    if not tasks:
        return "No previous tasks."

    output = []

    for item in tasks:
        output.append(
            f"""
Task:
{item["task"]}

Mode:
{item["mode"]}

Success:
{item["success"]}

Commit:
{item["commit"]}
"""
        )

    return "\n".join(output)
