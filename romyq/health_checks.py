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


def detect_planner_loops(
    memory_path: str,
    straight_threshold: int = 3,
    oscillation_min: int = 4,
    history_limit: int = 30,
) -> list[str]:
    """Detect planner cycling patterns using execution memory.

    Returns a list of human-readable warning strings.
    """
    from . import memory as mem_mod
    from .loop_detector import detect

    fps = mem_mod.recent_fingerprints(memory_path, limit=history_limit)
    patterns = detect(fps, straight_threshold=straight_threshold, oscillation_min=oscillation_min)
    return [p.description for p in patterns]


_STALE_CONTEXT_DAYS = 7          # context.md older than this → warning
_RECURRING_FAILURE_MIN = 5       # same reason in last 10 failures → warning


def detect_stale_artifacts(
    workspace_path: str,
    memory_path: str = "",
    history_path: str = "",
    context_text: str = "",
) -> list[str]:
    """Check for stale context.md and knowledge.json.

    Returns a list of warning strings; empty list means no staleness.
    """
    import pathlib
    from . import store

    warnings: list[str] = []

    ctx_path = store.context_path(workspace_path)
    if not pathlib.Path(ctx_path).exists():
        warnings.append(
            "context.md is absent — run 'romyq learn' to generate repository memory."
        )
    else:
        import time
        age_s = time.time() - pathlib.Path(ctx_path).stat().st_mtime
        age_days = age_s / 86400
        if age_days > _STALE_CONTEXT_DAYS:
            warnings.append(
                f"context.md is {int(age_days)} days old — run 'romyq learn' to refresh."
            )

    know_path = store.knowledge_path(workspace_path)
    if memory_path or history_path:
        from . import knowledge as know_mod
        if know_mod.is_stale(know_path, memory_path or "", history_path or "", context_text):
            warnings.append(
                "knowledge.json is stale — knowledge will be refreshed on next 'romyq run'."
            )

    return warnings


def detect_recurring_failures(history_path: str, window: int = 10, threshold: int = 5) -> list[str]:
    """Detect a single failure reason dominating the recent history.

    Returns a warning string if threshold out of the last window failures share
    the same root cause.  Returns [] when history is healthy.
    """
    warnings: list[str] = []
    recent_entries = history_recent(limit=window, path=history_path)
    failed = [e for e in recent_entries if not e.get("success")]
    if len(failed) < threshold:
        return warnings
    reason_counts: dict[str, int] = {}
    for e in failed:
        r = e.get("validation_reason", "")
        if r:
            reason_counts[r] = reason_counts.get(r, 0) + 1
    for reason, count in reason_counts.items():
        if count >= threshold:
            preview = reason[:80].replace("\n", " ")
            warnings.append(
                f"Excessive recurring failures: '{preview}' seen {count} times "
                f"in the last {len(failed)} failures."
            )
    return warnings


def detect_stuck_conditions(
    state: dict,
    history_path: str,
    events_path: str,
    heartbeat_age_s: int | None = None,
    memory_path: str = "",
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

    # ── 6. Planner loop detection (from execution memory) ─────────────────────
    if memory_path:
        loop_warnings = detect_planner_loops(memory_path)
        warnings.extend(loop_warnings)

    # ── 7. Excessive recurring failures ───────────────────────────────────────
    recurring = detect_recurring_failures(history_path)
    warnings.extend(recurring)

    return warnings
