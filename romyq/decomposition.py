"""Mission decomposition — generate an advisory task plan before first execution.

Creates .romyq/plan.json with a flat list of tasks derived from the mission.
The plan is advisory: the dynamic DeepSeek planner still drives actual task
selection.  The plan only informs the dashboard progress display.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_VERSION = 1
_TASK_STATUSES = frozenset({"pending", "active", "completed", "skipped"})

_SYSTEM_PROMPT = (
    "You are a senior software architect. "
    "Generate a concise, ordered task breakdown."
)

_DECOMPOSE_PROMPT = """\
Break down this software project mission into 5-15 concrete implementation tasks.

Mission:
{mission}

Rules:
- Each task must be independently completable and end with a git commit.
- Tasks should follow logical implementation order.
- Be specific: name the files, modules, or endpoints to implement.
- No planning, documentation, or discussion tasks.

Output ONLY a numbered list, one task per line:
1. First task
2. Second task
...
"""


# ── persistence ───────────────────────────────────────────────────────────────

def _empty() -> dict:
    return {
        "version": _VERSION,
        "generated_at": "",
        "mission": "",
        "tasks": [],
    }


def load_plan(plan_path: str) -> dict:
    """Load plan.json, returning an empty structure on missing or corrupt."""
    try:
        with open(plan_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("tasks", [])
        data.setdefault("version", _VERSION)
        data.setdefault("mission", "")
        data.setdefault("generated_at", "")
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty()


def _write_atomic(plan_path: str, data: dict) -> None:
    dir_ = os.path.dirname(os.path.abspath(plan_path))
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, plan_path)


def write_plan(plan_path: str, data: dict) -> str:
    """Atomically write plan.json. Returns the path."""
    _write_atomic(plan_path, data)
    return plan_path


# ── parsing ───────────────────────────────────────────────────────────────────

def _parse_tasks(text: str) -> list[dict]:
    """Extract a task list from LLM output (numbered or bulleted lines)."""
    tasks: list[dict] = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r'^(?:\d+[.)]\s+|[-*•]\s+)(.+)', line)
        if m:
            task_text = m.group(1).strip()
            if len(task_text) > 5:
                tasks.append({"text": task_text, "status": "pending"})
    return tasks


# ── decomposition (requires DeepSeek) ────────────────────────────────────────

def decompose(
    api_key: str,
    mission: str,
) -> dict:
    """Call DeepSeek to decompose mission into an ordered task list.

    Returns a plan dict ready to write.  Never raises — returns an empty plan
    on API failure.
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")
        prompt = _DECOMPOSE_PROMPT.format(mission=mission[:2000])
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
        raw = response.choices[0].message.content.strip()
        tasks = _parse_tasks(raw)
    except Exception:
        tasks = []

    return {
        "version": _VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "mission": mission[:500],
        "tasks": tasks,
    }


# ── task status management ────────────────────────────────────────────────────

def _update_task(plan_path: str, task_text: str, status: str) -> bool:
    if status not in _TASK_STATUSES:
        return False
    data = load_plan(plan_path)
    needle = task_text.lower().strip()
    for task in data.get("tasks", []):
        if task.get("text", "").lower().strip() == needle:
            task["status"] = status
            _write_atomic(plan_path, data)
            return True
    return False


def mark_active(plan_path: str, task_text: str) -> bool:
    return _update_task(plan_path, task_text, "active")


def mark_completed(plan_path: str, task_text: str) -> bool:
    return _update_task(plan_path, task_text, "completed")


def mark_skipped(plan_path: str, task_text: str) -> bool:
    return _update_task(plan_path, task_text, "skipped")


def reset_active_tasks(plan_path: str) -> None:
    """Reset any active tasks to pending (called on loop restart)."""
    data = load_plan(plan_path)
    changed = False
    for task in data.get("tasks", []):
        if task.get("status") == "active":
            task["status"] = "pending"
            changed = True
    if changed:
        _write_atomic(plan_path, data)


# ── summary ───────────────────────────────────────────────────────────────────

def plan_summary(plan_path: str) -> dict:
    """Return task counts by status."""
    data = load_plan(plan_path)
    tasks = data.get("tasks", [])
    counts: dict[str, int] = {s: 0 for s in _TASK_STATUSES}
    for t in tasks:
        s = t.get("status", "pending")
        counts[s] = counts.get(s, 0) + 1
    return {"total": len(tasks), **counts}


def format_plan(plan_path: str, max_tasks: int = 20) -> str:
    """Return a human-readable plan display string."""
    data = load_plan(plan_path)
    tasks = data.get("tasks", [])
    if not tasks:
        return "(no plan generated)"
    icons = {"pending": "□", "active": "→", "completed": "✓", "skipped": "–"}
    lines: list[str] = []
    for task in tasks[:max_tasks]:
        icon = icons.get(task.get("status", "pending"), "□")
        lines.append(f"  {icon} {task['text']}")
    if len(tasks) > max_tasks:
        lines.append(f"  … ({len(tasks) - max_tasks} more tasks)")
    return "\n".join(lines)
