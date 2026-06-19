"""Steering console — operator instructions during active loop execution.

Instructions are stored as operator_instruction events in events.log and
injected into every DeepSeek planning call via instructions_text().
"""
from __future__ import annotations

OPERATOR_INSTRUCTION = "operator_instruction"


def record_instruction(events_path: str, instruction: str) -> None:
    """Record an operator instruction to the event log."""
    text = instruction.strip()[:500]
    if not text:
        return
    from .events import emit
    emit(events_path, OPERATOR_INSTRUCTION, instruction=text)


def recent_instructions(events_path: str, limit: int = 5) -> list[str]:
    """Return the most recent operator instructions from the event log."""
    from .events import tail
    events = tail(events_path, n=300)
    result: list[str] = []
    for e in events:
        if e.get("event") == OPERATOR_INSTRUCTION:
            text = e.get("instruction", "").strip()
            if text:
                result.append(text)
    return result[-limit:] if result else []


def instructions_text(events_path: str, limit: int = 5) -> str:
    """Return a formatted prompt section with recent operator instructions.

    Returns '' when no instructions exist.
    """
    instructions = recent_instructions(events_path, limit=limit)
    if not instructions:
        return ""
    lines = ["## Operator Instructions (highest priority — follow these exactly)\n"]
    for instruction in instructions:
        lines.append(f"- {instruction}")
    return "\n".join(lines)


def clear_instructions(events_path: str) -> None:
    """Emit a sentinel event that marks all prior instructions as cleared."""
    from .events import emit
    emit(events_path, "operator_instructions_cleared")


def instruction_count(events_path: str) -> int:
    """Return total operator instruction count in the event log."""
    from .events import tail
    events = tail(events_path, n=10_000)
    return sum(1 for e in events if e.get("event") == OPERATOR_INSTRUCTION)
