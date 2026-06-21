"""Recommendation engine — evaluates project state and returns Continue/Pause/Review/Stop.

Takes readiness, lifecycle, state, and profile as inputs.
Always returns a recommendation dict:
{
  "recommendation": "Continue" | "Pause" | "Review" | "Stop",
  "reason": "...",
  "readiness": 75,
  "phases_complete": 2,
  "total_phases": 4,
  "done_criteria_met": ["software runs"],
  "done_criteria_pending": ["tests pass", "README exists"],
}
"""
from __future__ import annotations


_VALID = frozenset({"Continue", "Pause", "Review", "Stop"})


def _make(
    recommendation: str,
    reason: str,
    readiness: float = 0,
    phases_complete: int = 0,
    total_phases: int = 0,
    criteria_met: list[str] | None = None,
    criteria_pending: list[str] | None = None,
) -> dict:
    return {
        "recommendation": recommendation,
        "reason": reason,
        "readiness": round(readiness, 1),
        "phases_complete": phases_complete,
        "total_phases": total_phases,
        "done_criteria_met": criteria_met or [],
        "done_criteria_pending": criteria_pending or [],
    }


def _check_done_criteria(
    criteria: list[str],
    lifecycle: dict,
    state: dict,
) -> tuple[list[str], list[str]]:
    """Return (met, pending) lists by checking lifecycle and state for evidence."""
    phases = lifecycle.get("phases", [])
    phase_names_lower = {p.get("name", "").lower() for p in phases}
    complete_phase_names = {
        p.get("name", "").lower()
        for p in phases
        if p.get("status") == "complete"
    }
    all_tasks_lower = " ".join(
        t.get("text", "").lower()
        for p in phases
        for t in p.get("tasks", [])
    )
    completed_tasks_lower = " ".join(
        t.get("text", "").lower()
        for p in phases
        for t in p.get("tasks", [])
        if t.get("status") == "complete"
    )

    met: list[str] = []
    pending: list[str] = []

    for criterion in criteria:
        c = criterion.lower()
        satisfied = False

        if "software runs" in c or "software works" in c:
            caps = state.get("capabilities", {})
            core = caps.get("Core Features", {}).get("status", "missing")
            satisfied = core == "complete" or any(
                "core" in n or "implement" in n for n in complete_phase_names
            )

        elif "tests pass" in c or "tests" in c:
            caps = state.get("capabilities", {})
            testing = caps.get("Testing", {}).get("status", "missing")
            satisfied = (
                testing == "complete"
                or any("test" in n for n in complete_phase_names)
                or "test" in completed_tasks_lower
            )

        elif "readme" in c:
            satisfied = (
                any("doc" in n or "readme" in n for n in complete_phase_names)
                or "readme" in completed_tasks_lower
            )

        elif "ci passes" in c or "ci" in c:
            satisfied = (
                any("ci" in n or "deploy" in n for n in complete_phase_names)
                or "ci" in completed_tasks_lower
                or ".github" in completed_tasks_lower
            )

        elif "docs complete" in c or "documentation" in c:
            caps = state.get("capabilities", {})
            doc_status = caps.get("Documentation", {}).get("status", "missing")
            satisfied = doc_status == "complete" or any("doc" in n for n in complete_phase_names)

        elif "deployment ready" in c or "deployment" in c:
            caps = state.get("capabilities", {})
            dep_status = caps.get("Deployment", {}).get("status", "missing")
            satisfied = dep_status == "complete" or any("deploy" in n for n in complete_phase_names)

        elif "security" in c:
            caps = state.get("capabilities", {})
            sec_status = caps.get("Security", {}).get("status", "missing")
            satisfied = sec_status == "complete" or any("security" in n for n in complete_phase_names)

        if satisfied:
            met.append(criterion)
        else:
            pending.append(criterion)

    return met, pending


def recommend(
    readiness: dict,
    lifecycle: dict,
    state: dict,
    profile: dict,
) -> dict:
    """Evaluate project state and return a recommendation.

    Parameters
    ----------
    readiness : output of readiness.compute() or readiness.compute_from_path()
    lifecycle : loaded lifecycle.json dict
    state     : loaded state.json dict
    profile   : output of profile.config(level) dict — must have readiness_target
    """
    overall = readiness.get("overall", 0)
    threshold = profile.get("readiness_target", 75)

    phases = lifecycle.get("phases", [])
    total_phases = len(phases)
    complete_phases = sum(1 for p in phases if p.get("status") == "complete")
    all_done = total_phases > 0 and complete_phases == total_phases

    done_criteria_list = lifecycle.get("done_criteria", [])
    criteria_met, criteria_pending = _check_done_criteria(done_criteria_list, lifecycle, state)

    consecutive = state.get("consecutive_failures", 0)
    paused = state.get("paused", False) or state.get("pause_requested", False)

    # Operator pause takes top priority
    if paused:
        return _make(
            "Pause",
            "Operator requested pause",
            overall,
            complete_phases,
            total_phases,
            criteria_met,
            criteria_pending,
        )

    # Too many consecutive failures — human needed
    if consecutive >= 5:
        return _make(
            "Review",
            f"{consecutive} consecutive failures — manual intervention needed",
            overall,
            complete_phases,
            total_phases,
            criteria_met,
            criteria_pending,
        )

    # All phases done and all criteria met — recommend Stop.
    # Readiness threshold is a soft gate for early stopping only; it does not
    # block termination when the lifecycle has completed its defined work.
    if all_done and not criteria_pending:
        return _make(
            "Stop",
            f"All phases complete, done criteria satisfied (readiness {overall:.0f}%)",
            overall,
            complete_phases,
            total_phases,
            criteria_met,
            criteria_pending,
        )

    # All phases done but criteria not met — something to review
    if all_done and criteria_pending:
        pending_str = ", ".join(criteria_pending[:3])
        return _make(
            "Review",
            f"All phases complete but criteria not yet satisfied: {pending_str}",
            overall,
            complete_phases,
            total_phases,
            criteria_met,
            criteria_pending,
        )

    # Readiness above threshold but work remains — keep going
    if overall >= threshold and not all_done:
        return _make(
            "Continue",
            f"Readiness {overall:.0f}% — {total_phases - complete_phases} phase(s) remaining",
            overall,
            complete_phases,
            total_phases,
            criteria_met,
            criteria_pending,
        )

    # Default — keep going
    return _make(
        "Continue",
        f"Readiness {overall:.0f}% / target {threshold}% — project in progress",
        overall,
        complete_phases,
        total_phases,
        criteria_met,
        criteria_pending,
    )


def recommend_from_paths(
    readiness_path: str | None = None,
    lifecycle_path: str | None = None,
    state_path: str | None = None,
    profile_path: str | None = None,
    workspace_path: str | None = None,
) -> dict:
    """Convenience wrapper that loads all data from file paths."""
    from romyq import store
    from romyq import readiness as rdns
    from romyq import lifecycle as lc
    from romyq import profile as pf
    from romyq.state import load as load_state

    ws = workspace_path or "."

    r_path = readiness_path or store.project_state_path(ws)
    l_path = lifecycle_path or store.lifecycle_path(ws)
    s_path = state_path or store.state_path(ws)
    p_path = profile_path or store.profile_path(ws)

    readiness_data = rdns.compute_from_path(r_path)
    lifecycle_data = lc.load(l_path)
    state_data = load_state(s_path)
    complexity = pf.get_complexity(p_path)
    profile_data = pf.config(complexity)

    return recommend(readiness_data, lifecycle_data, state_data, profile_data)


def format_recommendation(result: dict) -> str:
    """Return a human-readable recommendation display."""
    rec = result.get("recommendation", "Continue")
    reason = result.get("reason", "")
    overall = result.get("readiness", 0)
    phases_complete = result.get("phases_complete", 0)
    total_phases = result.get("total_phases", 0)
    met = result.get("done_criteria_met", [])
    pending = result.get("done_criteria_pending", [])

    icons = {"Continue": "▶", "Pause": "⏸", "Review": "⚠", "Stop": "■"}
    icon = icons.get(rec, "▶")

    lines = [
        f"{icon} Recommendation: {rec}",
        f"  Reason    : {reason}",
        f"  Readiness : {overall:.1f}%",
        f"  Phases    : {phases_complete}/{total_phases} complete",
    ]
    if met:
        lines.append(f"  Done (met): {', '.join(met)}")
    if pending:
        lines.append(f"  Pending   : {', '.join(pending)}")
    return "\n".join(lines)
