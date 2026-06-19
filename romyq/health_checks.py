"""Stuck detection for long-running autonomous loops.

All checks are read-only — no side effects, no writes.
Returns a list of human-readable warning strings; empty list means healthy.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .events import count_by_type, tail as events_tail
from .history import recent as history_recent


_STALE_HEARTBEAT_THRESHOLD_S = 1800       # 30 min
_SUCCESS_DROUGHT_THRESHOLD_S = 7200       # 2 hours
_EVIDENCE_REPEAT_MIN_COUNT = 3            # same evidence seen this many times = stuck


def detect_stuck_conditions(
    state: dict,
    history_path: str,
    events_path: str,
    heartbeat_age_s: int | None = None,
) -> list[str]:
    """Return a list of warning strings describing stuck conditions.

    Returns [] when the loop is healthy.
    """
    warnings: list[str] = []

    # ── 1. Task retried too many times ────────────────────────────────────────
    attempts = state.get("current_task_attempts", 0)
    ceiling = state.get("max_task_attempts", 3)
    task_key = state.get("current_task_key", "")
    if attempts >= ceiling and ceiling > 0 and task_key:
        warnings.append(
            f"Task retried {attempts} times (ceiling {ceiling}) — task is BLOCKED: key={task_key[:12]}"
        )

    consec = state.get("consecutive_failures", 0)
    if consec >= 5:
        warnings.append(f"{consec} consecutive failures without a successful task.")

    # ── 2. Validator evidence unchanged across recent failures ────────────────
    recent_entries = history_recent(limit=20, path=history_path)
    failed = [e for e in recent_entries if not e.get("success")]
    if len(failed) >= _EVIDENCE_REPEAT_MIN_COUNT:
        reasons = [e.get("validation_reason", "") for e in failed[-_EVIDENCE_REPEAT_MIN_COUNT:]]
        if len(set(reasons)) == 1 and reasons[0]:
            preview = reasons[0][:80].replace("\n", " ")
            warnings.append(
                f"Validator evidence unchanged across last {len(reasons)} failures: \"{preview}\""
            )

    # ── 3. No successful task for an extended period ───────────────────────────
    last_success_dt: datetime | None = None
    for entry in reversed(recent_entries):
        if entry.get("success"):
            ts = entry.get("timestamp", "")
            try:
                last_success_dt = datetime.fromisoformat(ts)
            except Exception:
                pass
            break

    if last_success_dt is not None:
        drought_s = int((datetime.now(timezone.utc) - last_success_dt).total_seconds())
        if drought_s >= _SUCCESS_DROUGHT_THRESHOLD_S:
            hrs = drought_s // 3600
            warnings.append(
                f"No successful task for {hrs}+ hour(s) (last success: {last_success_dt.strftime('%Y-%m-%d %H:%M')} UTC)."
            )
    elif recent_entries:
        # Have history but zero successes
        oldest_ts = recent_entries[0].get("timestamp", "")
        try:
            oldest_dt = datetime.fromisoformat(oldest_ts)
            drought_s = int((datetime.now(timezone.utc) - oldest_dt).total_seconds())
            if drought_s >= _SUCCESS_DROUGHT_THRESHOLD_S:
                warnings.append(
                    f"No successful task recorded in the last {len(recent_entries)} history entries."
                )
        except Exception:
            pass

    # ── 4. Stale heartbeat while in an active phase ───────────────────────────
    active_phases = {"executing", "validating", "planning", "rate_limited"}
    phase = state.get("phase", "idle")
    if phase in active_phases:
        if heartbeat_age_s is None:
            hb = state.get("heartbeat", "")
            if hb:
                try:
                    hb_dt = datetime.fromisoformat(hb)
                    heartbeat_age_s = int((datetime.now(timezone.utc) - hb_dt).total_seconds())
                except Exception:
                    heartbeat_age_s = None

        if heartbeat_age_s is not None and heartbeat_age_s >= _STALE_HEARTBEAT_THRESHOLD_S:
            mins = heartbeat_age_s // 60
            warnings.append(
                f"Heartbeat is {mins} minutes old while loop is in phase '{phase}' — process may be stuck."
            )

    # ── 5. Rate-limit storm ───────────────────────────────────────────────────
    counts = count_by_type(events_path)
    recent_events = events_tail(events_path, n=50)
    recent_rate_limits = sum(1 for e in recent_events if e.get("event") == "rate_limit_detected")
    if recent_rate_limits >= 3:
        warnings.append(
            f"Rate-limit hit {recent_rate_limits} times in the last 50 events — possible token exhaustion."
        )

    return warnings
