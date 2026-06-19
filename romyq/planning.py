"""Build enriched planning context for the DeepSeek task-generation prompt.

Injects recent failures, blocked-task evidence, repository memory, and
execution-memory failure patterns into every planning call so the planner
can avoid repeated failed approaches.
"""
from __future__ import annotations

from .findings import unresolved as findings_unresolved
from .history import recent as history_recent


def build_memory_context(memory_path: str, limit: int = 8) -> str:
    """Return a prompt section summarising the top failed tasks from memory.

    Returns '' when memory is empty or the path is absent.
    """
    if not memory_path:
        return ""
    from . import memory as mem_mod
    top = mem_mod.most_failed(memory_path, limit=limit)
    if not top:
        return ""

    lines = [f"## Execution Memory — Top Failed Tasks ({len(top)} shown)\n"]
    lines.append("These tasks have failed repeatedly. Avoid proposing them again.\n")
    for fp, count, preview, last_reason in top:
        task_preview = preview[:100].replace("\n", " ")
        reason_preview = last_reason[:80].replace("\n", " ") if last_reason else "unknown"
        lines.append(f"- [{count}x failed] {task_preview}")
        lines.append(f"  Last reason: {reason_preview}")
    return "\n".join(lines)


def build_planning_context(
    state: dict,
    findings_path: str,
    history_path: str,
    context_text: str = "",
    max_findings: int = 20,
    max_failures: int = 10,
    memory_path: str = "",
) -> str:
    """Return a prompt section to inject into the DeepSeek planning prompt.

    context_text: contents of .romyq/context.md (pass '' to omit).
    memory_path:  path to .romyq/memory.json (pass '' to omit).
    """
    parts: list[str] = []

    # ── Repository memory ─────────────────────────────────────────────────────
    if context_text.strip():
        parts.append("## Repository Context\n\n" + context_text.strip())

    # ── Execution memory — top failed tasks ──────────────────────────────────
    mem_ctx = build_memory_context(memory_path)
    if mem_ctx:
        parts.append(mem_ctx)

    # ── Recent failures (from history.json) ───────────────────────────────────
    all_entries = history_recent(limit=50, path=history_path)
    failures = [e for e in all_entries if not e.get("success")][-max_failures:]
    if failures:
        lines = ["## Recent Failures (do not repeat these approaches)\n"]
        for i, f in enumerate(failures, 1):
            reason = f.get("validation_reason", "unknown")
            task_preview = f.get("task", "")[:120].replace("\n", " ")
            lines.append(f"{i}. [{reason[:60]}]  {task_preview}")
        parts.append("\n".join(lines))

    # ── Blocked task ──────────────────────────────────────────────────────────
    task_key = state.get("current_task_key", "")
    attempts = state.get("current_task_attempts", 0)
    ceiling = state.get("max_task_attempts", 3)
    last_reason = state.get("last_failure_reason", "")
    if task_key and attempts >= ceiling and ceiling > 0:
        blocked_lines = [
            "## Blocked Task Warning",
            "",
            f"The previous task (key: {task_key[:12]}) is BLOCKED after {attempts} attempts.",
        ]
        if last_reason:
            blocked_lines.append(f"Last failure reason: {last_reason[:200]}")
        blocked_lines.append(
            "Do NOT generate the same task. Choose a different approach or a prerequisite task."
        )
        parts.append("\n".join(blocked_lines))

    # ── Last validation evidence ──────────────────────────────────────────────
    evidence = state.get("last_validation_evidence", [])
    if evidence:
        ev_lines = ["## Last Validator Evidence\n"]
        ev_lines += [f"- {e}" for e in evidence[:10]]
        ev_lines.append(
            "\nDo not generate a task that would produce the same validator evidence."
        )
        parts.append("\n".join(ev_lines))

    # ── Unresolved findings ───────────────────────────────────────────────────
    items = findings_unresolved(findings_path)[-max_findings:]
    if items:
        f_lines = [f"## Unresolved Findings ({len(items)} total)\n"]
        for f in items:
            sev = f.get("severity", "medium").upper()[:4]
            f_lines.append(f"[{sev}] {f['title'][:80]}")
        parts.append("\n".join(f_lines))

    if not parts:
        return ""

    header = "─" * 60 + "\nPlanning Context (use this to avoid past mistakes)\n" + "─" * 60
    return header + "\n\n" + "\n\n".join(parts) + "\n" + "─" * 60
