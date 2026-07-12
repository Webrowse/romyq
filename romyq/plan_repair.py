"""Smart plan repair — regenerate failed task sections without restarting the mission.

When multiple tasks fail consecutively, repair_plan() asks DeepSeek to generate
replacement tasks for the blocked section.  The mission is NOT restarted;
only the failed portion of the plan is regenerated.
"""
from __future__ import annotations

import re

_REPAIR_THRESHOLD = 3   # consecutive/recent failures to trigger repair
_REPAIR_WINDOW = 5      # look back this many history entries

_REPAIR_PROMPT = """\
Several tasks in the implementation plan have failed recently.
Generate {n} replacement tasks that avoid the same failure patterns.

Mission:
{mission}

Failed tasks (do NOT repeat these):
{failed_tasks}

Recent failure reasons:
{failure_reasons}

Rules:
- Each replacement task must be independently completable and end with a git commit.
- Be specific: name the files, modules, or endpoints to implement.
- Avoid the approaches that caused the recent failures.
- Do NOT restart the whole mission — fix the blocked section only.

Output ONLY a numbered list, one task per line:
1. First replacement task
2. Second replacement task
...
"""


def needs_repair(history_path: str, window: int = _REPAIR_WINDOW, threshold: int = _REPAIR_THRESHOLD) -> bool:
    """Return True when >= threshold of the last `window` tasks failed."""
    from .history import recent
    entries = recent(limit=window, path=history_path)
    if len(entries) < threshold:
        return False
    failures = sum(1 for e in entries if not e.get("success", True))
    return failures >= threshold


def recent_failures(history_path: str, window: int = _REPAIR_WINDOW) -> list[dict]:
    """Return recent failed history entries."""
    from .history import recent
    entries = recent(limit=window, path=history_path)
    return [e for e in entries if not e.get("success", True)]


def _parse_repair_tasks(text: str) -> list[str]:
    """Extract task texts from numbered LLM output."""
    tasks = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r'^(?:\d+[.)]\s+|[-*•]\s+)(.+)', line)
        if m:
            task_text = m.group(1).strip()
            if len(task_text) > 5:
                tasks.append(task_text)
    return tasks


def repair_plan(
    plan_path: str,
    api_key: str,
    mission: str,
    history_path: str,
) -> dict:
    """Regenerate the failed portion of the plan using DeepSeek.

    - Failed tasks in the plan are marked as skipped.
    - New replacement tasks are appended as pending.
    - Returns the updated plan dict.
    - Never raises; returns the existing plan unchanged on any error.
    """
    from .decomposition import load_plan, write_plan, _parse_tasks

    data = load_plan(plan_path)
    failed_entries = recent_failures(history_path, window=_REPAIR_WINDOW)
    if not failed_entries:
        return data

    n_repair = len(failed_entries)
    failed_task_texts = [e.get("task", "")[:120].replace("\n", " ") for e in failed_entries]
    failure_reasons = [e.get("validation_reason", "unknown")[:80] for e in failed_entries]

    # Mark matching pending/active plan tasks as skipped
    failed_lower = {t.lower()[:60] for t in failed_task_texts}
    for task in data.get("tasks", []):
        text_lower = task.get("text", "").lower()[:60]
        if task.get("status") in ("pending", "active") and text_lower in failed_lower:
            task["status"] = "skipped"

    # Ask DeepSeek for replacements
    new_tasks: list[dict] = []
    try:
        from .provider import chat as provider_chat
        prompt = _REPAIR_PROMPT.format(
            n=n_repair,
            mission=mission[:1500],
            failed_tasks="\n".join(f"- {t}" for t in failed_task_texts),
            failure_reasons="\n".join(f"- {r}" for r in failure_reasons),
        )
        raw = provider_chat(
            api_key,
            [
                {"role": "system", "content": "You are a senior software architect."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.4,
            max_tokens=512,
        )
        new_tasks = [{"text": t, "status": "pending"} for t in _parse_tasks(raw)]
    except Exception:
        pass

    if new_tasks:
        data["tasks"].extend(new_tasks)

    try:
        write_plan(plan_path, data)
    except Exception:
        pass

    return data
