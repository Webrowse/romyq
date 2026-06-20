"""Project timeline — describes project evolution in capability-level terms.

Instead of "Task #17 complete" the timeline says "Added Authentication".
Built from the task history's successful entries.
"""
from __future__ import annotations

import json
import os
from datetime import timezone


def _load_history(history_path: str, limit: int) -> list[dict]:
    try:
        with open(history_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return data[-limit:]
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _infer_capability(task: str) -> str:
    """Return the best capability name for a task, or '' for unknown."""
    from .capabilities import infer_capability_from_task
    return infer_capability_from_task(task)


def _summarize_task(task: str, max_len: int = 60) -> str:
    """Return a short, human-readable description of a task."""
    # Use first non-empty line
    for line in task.splitlines():
        line = line.strip().lstrip("-•* ").strip()
        if line:
            return line[:max_len] + ("…" if len(line) > max_len else "")
    return task[:max_len]


def _action_verb(capability: str) -> str:
    mapping = {
        "Authentication": "Added Authentication",
        "Authorization": "Added Authorization",
        "Database": "Set Up Database",
        "Testing": "Added Tests",
        "Validation": "Added Validation",
        "Search": "Added Search",
        "Documentation": "Added Documentation",
        "Security": "Hardened Security",
        "Observability": "Added Observability",
        "Deployment": "Configured Deployment",
        "Performance": "Improved Performance",
        "Core Features": "Built Core Features",
    }
    return mapping.get(capability, "")


def build_timeline(history_path: str, limit: int = 20) -> list[dict]:
    """Return timeline events describing project evolution, newest first.

    Each event:
      timestamp   ISO date string (date portion only)
      description Human-readable summary ("Added Authentication" etc.)
      capability  Best-matched capability or ''
      task        Raw task text (truncated)
    """
    all_entries = _load_history(history_path, limit * 5)
    successful = [e for e in all_entries if e.get("success")]
    # Deduplicate by capability (keep latest per capability)
    seen_caps: set[str] = set()
    unique_events: list[dict] = []
    for e in reversed(successful):
        cap = _infer_capability(e.get("task", ""))
        if cap and cap in seen_caps:
            continue
        if cap:
            seen_caps.add(cap)
        ts = e.get("timestamp", "")
        date = ts[:10] if ts else ""
        desc = _action_verb(cap) or _summarize_task(e.get("task", "Unknown task"))
        unique_events.append({
            "timestamp": date,
            "description": desc,
            "capability": cap,
            "task": _summarize_task(e.get("task", ""), 80),
        })
    # newest first, capped
    return unique_events[:limit]


def format_timeline(history_path: str, limit: int = 20) -> str:
    """Return a human-readable timeline string."""
    events = build_timeline(history_path, limit=limit)
    if not events:
        return "(no completed work yet)"
    lines = []
    for ev in events:
        date = ev.get("timestamp") or "unknown"
        desc = ev.get("description", "")
        cap = ev.get("capability", "")
        cap_tag = f"  [{cap}]" if cap else ""
        lines.append(f"  {date}  {desc}{cap_tag}")
    return "\n".join(lines)
