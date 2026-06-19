"""Startup recovery analysis for crash, SIGTERM, and power-loss scenarios.

Called at CLI explain-time and at loop startup to tell the operator (or the
loop itself) what happened since the last clean shutdown and what to do next.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple


class RecoveryState(NamedTuple):
    situation: str       # one-line description of what happened
    recommendation: str  # what the operator should do
    severity: str        # "ok" | "warning" | "error"


# ── heartbeat age ─────────────────────────────────────────────────────────────

def _heartbeat_age(state: dict) -> int:
    """Return seconds since last heartbeat, or -1 if unknown."""
    hb = state.get("heartbeat", "")
    if not hb:
        return -1
    try:
        hb_dt = datetime.fromisoformat(hb)
        return int((datetime.now(timezone.utc) - hb_dt).total_seconds())
    except Exception:
        return -1


# ── phase-specific recommendations ───────────────────────────────────────────

_PHASE_ADVICE: dict[str, tuple[str, str, str]] = {
    # phase → (situation, recommendation, severity)
    "executing": (
        "Loop was interrupted while Claude was executing.",
        "The workspace may be dirty. Run 'romyq explain' to check validator evidence, "
        "then 'romyq run' — the loop will validate the current state before proceeding.",
        "warning",
    ),
    "validating": (
        "Loop was interrupted during validation.",
        "Run 'romyq run' — the loop will re-run the validator on the current workspace state.",
        "warning",
    ),
    "planning": (
        "Loop was interrupted while requesting a task from the planner.",
        "Run 'romyq run' — the loop will re-plan from the current repository state.",
        "warning",
    ),
    "stopping": (
        "Loop was in the process of stopping when it was interrupted.",
        "Run 'romyq run' to restart, or leave it stopped if that was intended.",
        "warning",
    ),
    "stopped": (
        "Loop stopped gracefully.",
        "Run 'romyq run' to restart.",
        "ok",
    ),
    "paused": (
        "Loop is paused.",
        "Run 'romyq resume' to continue, or 'romyq run' to restart.",
        "ok",
    ),
    "rate_limited": (
        "Loop was interrupted while sleeping through a rate-limit window.",
        "Run 'romyq run' — rate-limit state will be cleared and the task retried.",
        "warning",
    ),
    "idle": (
        "Loop stopped cleanly between tasks.",
        "Run 'romyq run' to continue.",
        "ok",
    ),
    "failed": (
        "Loop entered FAILED state due to repeated failures.",
        "Review 'romyq explain' for failure details, then run 'romyq run' to retry.",
        "error",
    ),
}


def analyze_recovery_state(
    state: dict,
    heartbeat_age_s: int | None = None,
) -> RecoveryState:
    """Produce a recovery recommendation from state.json content.

    heartbeat_age_s: seconds since last heartbeat; computed from state if None.
    """
    phase = state.get("phase", "idle")
    age = heartbeat_age_s if heartbeat_age_s is not None else _heartbeat_age(state)
    task = state.get("current_task", "").strip()
    attempts = state.get("current_task_attempts", 0)
    ceiling = state.get("max_task_attempts", 3)
    consec = state.get("consecutive_failures", 0)
    paused = state.get("paused", False)
    stop_req = state.get("stop_requested", False)

    # Override phase with explicit flag state first
    if stop_req and phase not in ("stopped", "stopping"):
        return RecoveryState(
            situation="A stop was requested but the loop did not exit cleanly.",
            recommendation="Run 'romyq run' to restart (stop_requested will be cleared), "
                           "or 'romyq stop' to set it again if you intend to keep it stopped.",
            severity="warning",
        )

    if paused and phase not in ("paused",):
        return RecoveryState(
            situation="Loop is marked paused but the phase field shows it was not paused cleanly.",
            recommendation="Run 'romyq resume' then 'romyq run' to continue.",
            severity="warning",
        )

    # Task blocked
    if attempts >= ceiling and ceiling > 0 and phase in ("executing", "idle", "validating"):
        return RecoveryState(
            situation=f"Current task has been attempted {attempts}/{ceiling} times and is BLOCKED.",
            recommendation=(
                "The loop will skip this task on next run and record a finding. "
                "Review 'romyq explain' for validator evidence, then run 'romyq run'."
            ),
            severity="error",
        )

    # Stale heartbeat for active phases
    active_phases = {"executing", "validating", "planning", "rate_limited"}
    if phase in active_phases and age > 1800:
        mins = age // 60
        return RecoveryState(
            situation=f"Loop was in phase '{phase}' and last heartbeat was {mins} minutes ago.",
            recommendation=(
                "The process likely crashed or was killed mid-task. "
                "Run 'romyq explain' to check workspace state, then 'romyq run' to recover."
            ),
            severity="error",
        )

    # Consecutive failure streak
    if consec >= 5:
        return RecoveryState(
            situation=f"{consec} consecutive failures without a successful task.",
            recommendation=(
                "Review 'romyq explain' for failure patterns. "
                "Consider adding a steering note ('romyq note') to redirect the planner, "
                "then run 'romyq run'."
            ),
            severity="error",
        )

    # Use the phase table for everything else
    advice = _PHASE_ADVICE.get(phase)
    if advice:
        situation, recommendation, severity = advice
        if task and phase in ("executing", "validating", "planning"):
            preview = task[:120].replace("\n", " ")
            situation = f"{situation}  Task: {preview}"
        return RecoveryState(situation=situation, recommendation=recommendation, severity=severity)

    return RecoveryState(
        situation=f"Unknown phase '{phase}'.",
        recommendation="Run 'romyq run' to restart.",
        severity="warning",
    )
