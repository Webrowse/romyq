"""Planning guardrails — validate proposed tasks against the knowledge base.

Prevents the planner from re-proposing tasks that have failed repeatedly.
Integrates with knowledge.py (pattern store) and memory.py (similarity).
"""
from __future__ import annotations

from typing import NamedTuple


class GuardrailViolation(NamedTuple):
    task_preview: str
    reason: str
    fingerprint: str


def validate_task_against_knowledge(
    task: str,
    knowledge_path: str,
    memory_path: str = "",
    failure_threshold: int = 3,
) -> GuardrailViolation | None:
    """Check whether a proposed task should be rejected.

    Returns a GuardrailViolation when the task matches a known repeated failure
    pattern.  Returns None when the task is safe to proceed.

    knowledge_path:    path to .romyq/knowledge.json
    memory_path:       path to .romyq/memory.json (enables similarity check)
    failure_threshold: minimum failure count before a task is blocked
    """
    if not task or not task.strip():
        return None

    from . import knowledge as know_mod
    from .fingerprint import fingerprint as fp_fn, is_similar

    task_fp = fp_fn(task)
    task_preview = task[:80].replace("\n", " ")

    # ── Check 1: exact fingerprint match in knowledge failure patterns ─────────
    for pattern in know_mod.top_failure_patterns(knowledge_path):
        if pattern.get("count", 0) < failure_threshold:
            continue
        if pattern.get("fingerprint") == task_fp:
            last_reason = pattern.get("last_reason", "unknown")[:100]
            return GuardrailViolation(
                task_preview=task_preview,
                reason=(
                    f"Task matches a known failure pattern "
                    f"(failed {pattern['count']} times). "
                    f"Last reason: {last_reason}"
                ),
                fingerprint=task_fp,
            )

    # ── Check 2: similarity match in execution memory ─────────────────────────
    if memory_path:
        try:
            from . import memory as mem_mod
            top_failed = mem_mod.most_failed(memory_path, limit=20)
            for fp, count, preview, last_reason in top_failed:
                if count < failure_threshold:
                    continue
                if is_similar(task, preview):
                    lr = (last_reason or "unknown")[:100]
                    return GuardrailViolation(
                        task_preview=task_preview,
                        reason=(
                            f"Task is similar to a task that failed {count} times. "
                            f"Last reason: {lr}"
                        ),
                        fingerprint=task_fp,
                    )
        except Exception:
            pass

    return None


def build_guardrail_context(violation: GuardrailViolation) -> str:
    """Return a prompt section explaining the guardrail rejection to the planner."""
    return (
        "## Guardrail Rejection — Do NOT repeat this task\n\n"
        f"The proposed task was rejected:\n"
        f"  Task: {violation.task_preview}\n"
        f"  Reason: {violation.reason}\n\n"
        "Generate a DIFFERENT task that avoids this failure pattern.\n"
        "Specifically, do NOT propose the same task or close variations."
    )


def validate_and_retry(
    generate_fn,
    task: str,
    knowledge_path: str,
    memory_path: str = "",
    failure_threshold: int = 3,
    max_retries: int = 2,
) -> tuple[str, GuardrailViolation | None]:
    """Validate a task and retry generation if it violates a guardrail.

    generate_fn must accept a single string `extra_context` kwarg and return
    a new task string.  Returns (final_task, last_violation_or_None).
    """
    violation = validate_task_against_knowledge(
        task, knowledge_path, memory_path, failure_threshold
    )
    if violation is None:
        return task, None

    last_violation = violation
    for _ in range(max_retries):
        extra_ctx = build_guardrail_context(last_violation)
        try:
            new_task = generate_fn(extra_context=extra_ctx)
        except Exception:
            break
        new_violation = validate_task_against_knowledge(
            new_task, knowledge_path, memory_path, failure_threshold
        )
        if new_violation is None:
            return new_task, last_violation
        last_violation = new_violation
        task = new_task

    # Ran out of retries — return the last generated task anyway
    return task, last_violation
