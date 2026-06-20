"""Terminal visualization — progress bars, lifecycle charts, architecture flow."""
from __future__ import annotations

_FILL = "█"
_EMPTY = "░"


def progress_bar(pct: float, width: int = 12, fill: str = _FILL, empty: str = _EMPTY) -> str:
    """Return a text progress bar for the given percentage (0-100)."""
    pct = max(0.0, min(100.0, float(pct)))
    filled = round(width * pct / 100)
    return fill * filled + empty * (width - filled)


def format_phase_bars(lifecycle_data: dict, bar_width: int = 12) -> str:
    """Return a multi-line lifecycle progress chart with one bar per phase."""
    phases = lifecycle_data.get("phases", [])
    if not phases:
        return "(no lifecycle generated)"

    max_name = max((len(p.get("name", "")) for p in phases), default=10)
    label_w = min(max_name + 2, 32)

    lines: list[str] = []
    for phase in phases:
        name = phase.get("name", f"Phase {phase.get('id', '?')}")
        status = phase.get("status", "pending")
        pct = 100 if status == "complete" else float(phase.get("percentage_complete", 0))
        bar = progress_bar(pct, bar_width)
        icon = "✓" if status == "complete" else ("→" if status == "active" else "□")
        lines.append(f"  {icon} {name:<{label_w}}  {bar}  {pct:3.0f}%")

    return "\n".join(lines)


def format_overall_bar(lifecycle_data: dict, bar_width: int = 20) -> str:
    """Return the overall project progress bar."""
    phases = lifecycle_data.get("phases", [])
    if not phases:
        return f"  Overall: {progress_bar(0, bar_width)}    0%"

    total_tasks = sum(p.get("total_tasks", len(p.get("tasks", []))) for p in phases)
    done_tasks = sum(p.get("completed_tasks", 0) for p in phases)
    pct = int(done_tasks * 100 / total_tasks) if total_tasks else 0

    bar = progress_bar(pct, bar_width)
    return f"  Overall: {bar}  {pct}%  ({done_tasks}/{total_tasks} tasks)"


def format_architecture_flow(lifecycle_data: dict) -> str:
    """Return a vertical flow diagram of lifecycle phases with task counts and status."""
    phases = lifecycle_data.get("phases", [])
    if not phases:
        return "(no lifecycle generated)"

    max_name = max((len(p.get("name", "")) for p in phases), default=10)
    label_w = min(max_name + 2, 32)

    lines: list[str] = []
    for i, phase in enumerate(phases):
        name = phase.get("name", f"Phase {phase.get('id', '?')}")
        total = phase.get("total_tasks", len(phase.get("tasks", [])))
        status = phase.get("status", "pending")
        pct = 100 if status == "complete" else int(phase.get("percentage_complete", 0))

        icon = "✓" if status == "complete" else ("→" if status == "active" else " ")
        tag = f"[{status}]" if status != "pending" else ""
        task_str = f"{total} task{'s' if total != 1 else ''}"
        lines.append(f"  {icon} {i + 1}. {name:<{label_w}}  {task_str:<10}  {pct:3d}%  {tag}")

        if i < len(phases) - 1:
            lines.append("       ↓")

    return "\n".join(lines)


def format_lifecycle_preview(lifecycle_data: dict) -> str:
    """Return a compact lifecycle preview for display before execution starts."""
    phases = lifecycle_data.get("phases", [])
    if not phases:
        return "(no lifecycle generated)"

    lines: list[str] = []
    total_tasks = 0
    for phase in phases:
        name = phase.get("name", "Phase")
        n = phase.get("total_tasks", len(phase.get("tasks", [])))
        total_tasks += n
        lines.append(f"  {len(lines) + 1}. {name}  ({n} tasks)")

    criteria = lifecycle_data.get("done_criteria", [])
    lines.append(f"\nTotal: {total_tasks} tasks")
    if criteria:
        lines.append(f"Done criteria: {', '.join(criteria)}")

    return "\n".join(lines)


def format_project_overview(
    lifecycle_data: dict,
    readiness: dict,
    recommendation: dict,
    profile_cfg: dict,
    project_name: str = "",
) -> str:
    """Return the full project overview section."""
    phases = lifecycle_data.get("phases", [])
    total_phases = len(phases)
    total_tasks = sum(p.get("total_tasks", len(p.get("tasks", []))) for p in phases)
    done_tasks = sum(p.get("completed_tasks", 0) for p in phases)
    remaining = total_tasks - done_tasks

    overall = readiness.get("overall", 0)
    rec = recommendation.get("recommendation", "Continue")
    complexity = profile_cfg.get("label", "Intermediate")
    target = profile_cfg.get("readiness_target", 75)

    W = 18
    lines: list[str] = []
    if project_name:
        lines.append(f"  Project:        {project_name}")
    lines.append(f"  Complexity:     {complexity}")
    lines.append(f"  Phases:         {total_phases}")
    lines.append(f"  Tasks:          {total_tasks}")
    lines.append(f"  Completed:      {done_tasks}")
    lines.append(f"  Remaining:      {remaining}")
    lines.append(f"  Readiness:      {overall:.0f}%  (target: {target}%)")
    lines.append(f"  Recommendation: {rec}")

    return "\n".join(lines)
