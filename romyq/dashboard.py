"""Lifecycle-first project dashboard renderer.

Renders the complete operator view answering the 8 key questions:
  1. What is being built?
  2. Which phase is active?
  3. How many phases remain?
  4. How complete is the project?
  5. What is Romyq doing right now?
  6. Why is it doing it?
  7. Should I continue running?
  8. Can I stop now?

All within a single `romyq dashboard` call.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import TextIO


_SEP = "─" * 60
_THICK = "━" * 60


def _safe_load(fn, *args, default=None):
    try:
        return fn(*args)
    except Exception:
        return default if default is not None else {}


def _load_all(workspace_path: str) -> dict:
    """Load every data source needed for the dashboard."""
    from . import store
    from .lifecycle import load as lc_load, progress_summary, current_phase
    from .readiness import compute_from_path
    from .recommendation import recommend
    from .profile import load as prof_load, get_complexity, config as prof_config
    from .state import load as load_state

    lc_data = _safe_load(lc_load, store.lifecycle_path(workspace_path), default={})
    prof_raw = _safe_load(prof_load, store.profile_path(workspace_path), default={})
    complexity = prof_raw.get("complexity", "intermediate")
    prof_cfg = _safe_load(prof_config, complexity, default={})
    rdns = _safe_load(compute_from_path, store.project_state_path(workspace_path), default={"overall": 0, "label": "Not Ready", "categories": {}})
    state = _safe_load(load_state, store.state_path(workspace_path), default={})
    rec = _safe_load(recommend, rdns, lc_data, state, prof_cfg, default={"recommendation": "Continue", "reason": "", "readiness": 0, "phases_complete": 0, "total_phases": 0, "done_criteria_met": [], "done_criteria_pending": []})

    try:
        from .mission import load as load_mission
        mission_text = load_mission(workspace_path)
        first_line = mission_text.strip().splitlines()[0].lstrip("#").strip()
        project_name = first_line[:60]
    except Exception:
        project_name = ""

    phases = lc_data.get("phases", [])
    summ: dict = {}
    if phases:
        from .lifecycle import progress_summary as _ps
        summ = _ps(lc_data)

    cur_phase: dict | None = None
    if phases:
        from .lifecycle import current_phase as _cp
        cur_phase = _cp(lc_data)

    return {
        "lc_data": lc_data,
        "prof_cfg": prof_cfg,
        "complexity": complexity,
        "rdns": rdns,
        "state": state,
        "rec": rec,
        "project_name": project_name,
        "phases": phases,
        "summ": summ,
        "cur_phase": cur_phase,
    }


def render(workspace_path: str, *, out: TextIO | None = None) -> None:
    """Print the full lifecycle-first dashboard to *out* (default: stdout)."""
    if out is None:
        out = sys.stdout

    def pr(*args, **kwargs) -> None:
        print(*args, file=out, **kwargs)

    d = _load_all(workspace_path)
    lc_data = d["lc_data"]
    prof_cfg = d["prof_cfg"]
    rdns = d["rdns"]
    state = d["state"]
    rec = d["rec"]
    project_name = d["project_name"]
    phases = d["phases"]
    summ = d["summ"]
    cur_phase = d["cur_phase"]

    overall_pct = rdns.get("overall", 0)
    rec_str = rec.get("recommendation", "Continue")
    rec_reason = rec.get("reason", "")
    complexity_label = prof_cfg.get("label", "Intermediate")

    # ── header ────────────────────────────────────────────────────────────────
    pr()
    if project_name:
        pr(f"  {project_name:<44} Readiness {overall_pct:.0f}%")
    else:
        pr(f"  (no mission)                                 Readiness {overall_pct:.0f}%")
    pr()

    # ── key metrics ───────────────────────────────────────────────────────────
    pr(f"  Complexity:     {complexity_label}")
    if summ:
        pr(f"  Phases:         {summ['complete_phases']}/{summ['total_phases']} complete")
        pr(f"  Tasks:          {summ['completed_tasks']}/{summ['total_tasks']} complete")
        pr(f"  Remaining:      {summ['remaining_tasks']} tasks")
    rec_icons = {"Continue": "▶", "Pause": "⏸", "Review": "⚠", "Stop": "■"}
    icon = rec_icons.get(rec_str, "▶")
    pr(f"  Recommendation: {icon} {rec_str}")
    pr()

    # ── lifecycle roadmap ─────────────────────────────────────────────────────
    lc_source = lc_data.get("source", "")
    _source_tag = ""
    if lc_source == "local_fallback":
        _source_tag = "  ⚠ local fallback — DeepSeek unavailable"
    elif lc_source == "deepseek":
        _source_tag = "  ✓ DeepSeek"
    pr(_THICK)
    pr(f"  Lifecycle{_source_tag}")
    pr(_THICK)
    pr()

    if phases:
        from .viz import format_phase_bars, format_overall_bar
        pr(format_phase_bars(lc_data))
        pr()
        pr(format_overall_bar(lc_data))
    else:
        pr("  No lifecycle found.")
        pr("  A lifecycle is generated when 'romyq run' starts.")
    pr()

    # ── current phase ─────────────────────────────────────────────────────────
    if cur_phase:
        pr(_SEP)
        pct = cur_phase.get("percentage_complete", 0)
        done = cur_phase.get("completed_tasks", 0)
        total = cur_phase.get("total_tasks", 0)
        pr(f"  Current Phase: {cur_phase['name']}")
        pr(f"  Progress:      {done}/{total} tasks  ({pct}%)")

        current_task = state.get("current_task", "")
        if current_task:
            task_preview = current_task.replace("\n", " ")[:80]
            if len(current_task.replace("\n", " ")) > 80:
                task_preview += "…"
            pr(f"  Current Task:  {task_preview}")

        loop_phase = state.get("phase", "")
        if loop_phase and loop_phase not in ("idle", "stopped"):
            pr(f"  Current Step:  {loop_phase}")

        expl = state.get("task_explanation", {})
        cap = expl.get("capability", "")
        reason = expl.get("reason", "")
        if cap or reason:
            pr(f"  Working on:    {cap or reason}")
        pr()

    # ── done criteria ─────────────────────────────────────────────────────────
    crit = lc_data.get("done_criteria", [])
    if crit:
        pr(_SEP)
        pr("  Done Criteria:")
        met = set(rec.get("done_criteria_met", []))
        for c in crit:
            mark = "✓" if c in met else "□"
            pr(f"    {mark} {c}")
        pr()

    # ── recommendation banner ─────────────────────────────────────────────────
    pr(_THICK)
    pr(f"  {icon} Recommendation: {rec_str}")
    if rec_reason:
        pr(f"    {rec_reason}")
    target = prof_cfg.get("readiness_target", 75)
    pr(f"    Readiness {overall_pct:.0f}% / target {target}%")
    pr(_THICK)
    pr()


def render_task_header(workspace_path: str, *, out: TextIO | None = None) -> None:
    """Print a compact one-line task header for the execution loop."""
    if out is None:
        out = sys.stdout

    try:
        from . import store
        from .lifecycle import load as lc_load, current_phase, progress_summary
        from .readiness import compute_from_path
        from .recommendation import recommend
        from .profile import get_complexity, config as prof_config
        from .state import load as load_state

        lc_data = lc_load(store.lifecycle_path(workspace_path))
        rdns = compute_from_path(store.project_state_path(workspace_path))
        state = load_state(store.state_path(workspace_path))
        complexity = get_complexity(store.profile_path(workspace_path))
        prof_cfg = prof_config(complexity)
        rec = recommend(rdns, lc_data, state, prof_cfg)

        phase = current_phase(lc_data)
        overall = rdns.get("overall", 0)
        rec_str = rec.get("recommendation", "Continue")

        if phase:
            done = phase.get("completed_tasks", 0)
            total = phase.get("total_tasks", 0)
            pct = phase.get("percentage_complete", 0)
            phase_info = f"{phase['name']}  {done}/{total} tasks  {pct}%"
        else:
            summ = progress_summary(lc_data) if lc_data.get("phases") else {}
            if summ:
                phase_info = f"All phases complete  {summ['completed_tasks']}/{summ['total_tasks']} tasks"
            else:
                phase_info = ""

        parts = [phase_info] if phase_info else []
        parts.append(f"Readiness {overall:.0f}%")
        parts.append(rec_str)

        line = "  ──  ".join(parts)
        print(f"\n  {line}\n", file=out)
    except Exception:
        pass


def answers(workspace_path: str) -> dict:
    """Return a dict with answers to the 8 operator questions."""
    d = _load_all(workspace_path)
    cur_phase = d["cur_phase"]
    phases = d["phases"]
    summ = d["summ"]
    state = d["state"]
    rdns = d["rdns"]
    rec = d["rec"]

    complete_phases = summ.get("complete_phases", 0) if summ else 0
    total_phases = summ.get("total_phases", 0) if summ else 0

    return {
        "what_being_built": d["project_name"],
        "active_phase": cur_phase["name"] if cur_phase else None,
        "phases_remaining": total_phases - complete_phases,
        "completion_pct": summ.get("overall_percentage", 0) if summ else 0,
        "current_action": state.get("phase", "idle"),
        "current_task": state.get("current_task", ""),
        "recommendation": rec.get("recommendation", "Continue"),
        "can_stop": rec.get("recommendation") == "Stop",
    }
