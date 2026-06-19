"""Rule guardrails — validate proposed tasks against active project rules.

Rules starting with blocking prefixes (Never, Avoid, Do not) extract the
forbidden term and reject tasks that contain it.  Other rules are advisory
and only appear in the planning context via rules_text().
"""
from __future__ import annotations

from typing import NamedTuple

# Prefixes that indicate a blocking rule, longest-first so we strip greedily.
_BLOCKING_PREFIXES: tuple[str, ...] = (
    "never use ",
    "avoid using ",
    "do not use ",
    "don't use ",
    "never ",
    "avoid ",
    "do not ",
    "don't ",
)


class RuleViolation(NamedTuple):
    task_preview: str
    violated_rule: str
    rule_id: str


def _extract_blocker_term(rule_text: str) -> str | None:
    """Extract the term to block from a negating rule.

    Returns None for advisory rules like "Always X" or "Prefer Y".
    """
    lower = rule_text.lower().strip()
    for prefix in _BLOCKING_PREFIXES:
        if lower.startswith(prefix):
            term = lower[len(prefix):].strip()
            return term if term else None
    return None


def check_task_against_rules(
    task: str,
    rules_path: str,
) -> RuleViolation | None:
    """Check a proposed task against active project rules.

    Returns a RuleViolation if the task violates a blocking rule.
    Returns None if the task is compliant.
    """
    if not task or not task.strip():
        return None

    from .rules import list_rules

    task_lower = task.lower()
    task_preview = task[:80].replace("\n", " ")

    for rule in list_rules(rules_path):
        rule_text = rule.get("text", "")
        if not rule_text:
            continue
        term = _extract_blocker_term(rule_text)
        if term and term in task_lower:
            return RuleViolation(
                task_preview=task_preview,
                violated_rule=rule_text,
                rule_id=rule.get("id", ""),
            )

    return None


def build_rule_violation_context(violation: RuleViolation) -> str:
    """Return a prompt section instructing the planner to generate a different task."""
    return (
        "## Rule Violation — Task Rejected\n\n"
        f"The proposed task violates a project rule:\n"
        f"  Task:  {violation.task_preview}\n"
        f"  Rule:  {violation.violated_rule}\n\n"
        "Generate a DIFFERENT task that complies with all project rules.\n"
        "Do NOT propose any task that uses or mentions the forbidden item."
    )


def relevant_rules(task: str, rules_path: str) -> list[str]:
    """Return rule texts whose keywords appear in the task (for display in approval mode)."""
    if not task:
        return []
    from .rules import list_rules
    task_lower = task.lower()
    result: list[str] = []
    for rule in list_rules(rules_path):
        text = rule.get("text", "")
        if not text:
            continue
        # Any significant word (>3 chars) from the rule appears in the task
        words = [w for w in text.lower().split() if len(w) > 3]
        if any(w in task_lower for w in words):
            result.append(text)
    return result
