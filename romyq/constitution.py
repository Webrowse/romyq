"""Project Constitution — generates .romyq/project.md.

A single human-readable document that combines: mission, rules,
knowledge lessons, capabilities, readiness score, and current priorities.
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timezone


def _ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ── section builders ──────────────────────────────────────────────────────────

def _section_mission(workspace_path: str) -> str:
    mission_path = os.path.join(workspace_path, "mission.md")
    try:
        with open(mission_path, encoding="utf-8") as f:
            content = f.read().strip()
        return f"## Mission\n\n{content}"
    except FileNotFoundError:
        return "## Mission\n\n(mission.md not found)"


def _section_rules(rules_path: str) -> str:
    try:
        from .rules import list_rules
        rules = list_rules(rules_path)
    except Exception:
        rules = []
    if not rules:
        return "## Project Rules\n\n(no rules defined)"
    lines = ["## Project Rules", ""]
    for r in rules:
        lines.append(f"- [{r.get('id', '?')}] {r.get('text', '')}")
    return "\n".join(lines)


def _section_knowledge(knowledge_path: str, max_lessons: int = 10) -> str:
    try:
        import json
        with open(knowledge_path, encoding="utf-8") as f:
            data = json.load(f)
        patterns = data.get("patterns", [])
        lessons = [
            p.get("lesson") or p.get("pattern") or p.get("description", "")
            for p in patterns
            if p.get("type") == "success_pattern"
        ]
        lessons = [l for l in lessons if l][:max_lessons]
    except Exception:
        lessons = []
    if not lessons:
        return "## Knowledge Lessons\n\n(no lessons recorded yet)"
    lines = ["## Knowledge Lessons", ""]
    for lesson in lessons:
        lines.append(f"- {lesson}")
    return "\n".join(lines)


def _section_capabilities(project_state_path: str) -> str:
    try:
        from .capabilities import format_capabilities
        table = format_capabilities(project_state_path)
    except Exception:
        table = "(unavailable)"
    return f"## Capabilities\n\n{table}"


def _section_readiness(project_state_path: str) -> str:
    try:
        from .readiness import compute_from_path, format_readiness
        r = compute_from_path(project_state_path)
        report = format_readiness(r)
    except Exception:
        report = "(unavailable)"
    return f"## Mission Readiness\n\n{report}"


def _section_priorities(rules_path: str, events_path: str) -> str:
    lines = ["## Current Priorities", ""]
    # Recent operator instructions
    try:
        from .steering import recent_instructions
        instructions = recent_instructions(events_path, limit=3)
        if instructions:
            lines.append("### Operator Instructions")
            for inst in instructions:
                lines.append(f"- {inst}")
            lines.append("")
    except Exception:
        pass
    # Stop condition recommendation
    try:
        from .stop_conditions import evaluate
        from .readiness import compute_from_path
        import os
        # find project_state_path from same dir as rules_path
        ps_path = os.path.join(os.path.dirname(rules_path), "project_state.json")
        r = compute_from_path(ps_path)
        rec = evaluate(r, {})
        lines.append(f"### Recommendation: {rec['recommendation']}")
        for reason in rec.get("reasons", [])[:2]:
            lines.append(f"- {reason.replace('_', ' ')}")
        lines.append("")
    except Exception:
        pass
    return "\n".join(lines)


# ── main API ──────────────────────────────────────────────────────────────────

def generate(
    workspace_path: str,
    rules_path: str = "",
    knowledge_path: str = "",
    project_state_path: str = "",
    events_path: str = "",
) -> str:
    """Return the full project.md content as a string."""
    romyq_dir = os.path.join(workspace_path, ".romyq")
    if not rules_path:
        rules_path = os.path.join(romyq_dir, "rules.json")
    if not knowledge_path:
        knowledge_path = os.path.join(romyq_dir, "knowledge.json")
    if not project_state_path:
        project_state_path = os.path.join(romyq_dir, "project_state.json")
    if not events_path:
        events_path = os.path.join(romyq_dir, "events.log")

    sections = [
        f"# Project Constitution\n\n_Generated {_ts()}_",
        _section_mission(workspace_path),
        _section_rules(rules_path),
        _section_knowledge(knowledge_path),
        _section_capabilities(project_state_path),
        _section_readiness(project_state_path),
        _section_priorities(rules_path, events_path),
    ]
    return "\n\n---\n\n".join(sections) + "\n"


def write(
    workspace_path: str,
    rules_path: str = "",
    knowledge_path: str = "",
    project_state_path: str = "",
    events_path: str = "",
) -> str:
    """Write .romyq/project.md and return the file path."""
    content = generate(
        workspace_path,
        rules_path=rules_path,
        knowledge_path=knowledge_path,
        project_state_path=project_state_path,
        events_path=events_path,
    )
    romyq_dir = os.path.join(workspace_path, ".romyq")
    os.makedirs(romyq_dir, exist_ok=True)
    out_path = os.path.join(romyq_dir, "project.md")
    dir_ = os.path.dirname(os.path.abspath(out_path))
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, out_path)
    return out_path
