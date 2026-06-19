"""Mission health score — a 0–100 composite score for the live dashboard.

Inputs: success rate, failure rate, blocked tasks, loop detections,
consecutive failures, and recovery events.

Grades:  A (85+)  B (70+)  C (55+)  D (40+)  F (<40)
"""
from __future__ import annotations

_GRADES = [
    (85, "A"),
    (70, "B"),
    (55, "C"),
    (40, "D"),
]


def _grade(score: int) -> str:
    for threshold, letter in _GRADES:
        if score >= threshold:
            return letter
    return "F"


def compute_health_score(
    history_path: str,
    events_path: str = "",
    state: dict | None = None,
) -> dict:
    """Compute a 0–100 mission health score.

    Returns:
        {
            "score":       int (0–100),
            "grade":       str ("A"–"F"),
            "components":  dict of named deductions/inputs,
        }
    """
    from .history import recent as history_recent
    from .events import count_by_type

    components: dict[str, object] = {}
    score = 100

    # ── success rate ──────────────────────────────────────────────────────────
    entries = history_recent(limit=100_000, path=history_path)
    total = len(entries)
    if total > 0:
        passed = sum(1 for e in entries if e.get("success"))
        sr = passed / total
    else:
        sr = 1.0
    components["success_rate"] = round(sr, 4)
    components["total_tasks"] = total

    if sr < 0.9:
        # Deduct up to 30 pts proportionally as SR falls below 0.9
        deduction = int((0.9 - sr) / 0.9 * 30)
        score -= min(deduction, 30)
        components["success_rate_penalty"] = -min(deduction, 30)
    else:
        components["success_rate_penalty"] = 0

    # ── consecutive failures from state ───────────────────────────────────────
    consec = 0
    if state:
        consec = state.get("consecutive_failures", 0)
    components["consecutive_failures"] = consec
    if consec > 0:
        consec_penalty = min(consec * 5, 20)
        score -= consec_penalty
        components["consecutive_failure_penalty"] = -consec_penalty
    else:
        components["consecutive_failure_penalty"] = 0

    # ── blocked tasks (from events) ───────────────────────────────────────────
    evt_counts: dict[str, int] = {}
    if events_path:
        evt_counts = count_by_type(events_path)

    blocked = evt_counts.get("task_blocked", 0)
    components["tasks_blocked"] = blocked
    if blocked > 0:
        blocked_penalty = min(blocked * 5, 15)
        score -= blocked_penalty
        components["blocked_task_penalty"] = -blocked_penalty
    else:
        components["blocked_task_penalty"] = 0

    # ── planner loops ─────────────────────────────────────────────────────────
    guardrails_hit = evt_counts.get("guardrail_triggered", 0)
    components["guardrails_triggered"] = guardrails_hit
    if guardrails_hit > 0:
        guardrail_penalty = min(guardrails_hit * 3, 15)
        score -= guardrail_penalty
        components["guardrail_penalty"] = -guardrail_penalty
    else:
        components["guardrail_penalty"] = 0

    # ── recovery bonus ────────────────────────────────────────────────────────
    recoveries = evt_counts.get("crash_recovered", 0)
    components["crash_recoveries"] = recoveries
    if recoveries > 0 and score < 100:
        bonus = min(recoveries * 3, 5)
        score = min(100, score + bonus)
        components["recovery_bonus"] = bonus
    else:
        components["recovery_bonus"] = 0

    score = max(0, min(100, score))
    return {
        "score": score,
        "grade": _grade(score),
        "components": components,
    }


def format_health_score(health: dict) -> str:
    """Return a short human-readable health summary string."""
    score = health.get("score", 0)
    grade = health.get("grade", "?")
    c = health.get("components", {})
    sr = c.get("success_rate", 0.0)
    return (
        f"Health: {score}/100  [{grade}]  "
        f"success_rate={sr * 100:.0f}%  "
        f"blocked={c.get('tasks_blocked', 0)}  "
        f"consec_failures={c.get('consecutive_failures', 0)}"
    )
