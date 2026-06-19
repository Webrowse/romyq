"""Long-run statistics derived from state.json, history.json, and events.log.

All metrics are read-only and computed on demand.  No new persistent state is
introduced — everything is derived from existing files so the metrics survive
restart automatically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import NamedTuple

from .events import count_by_type, tail as events_tail
from .history import recent as history_recent


class LoopMetrics(NamedTuple):
    """Snapshot of long-run operational statistics."""
    tasks_completed: int
    tasks_blocked: int
    history_entries: int
    success_count: int
    failure_count: int
    validator_pass_rate: float      # 0.0–1.0 (NaN → -1.0 when no history)
    cancellation_count: int
    rate_limit_count: int
    event_count: int
    first_event_ts: str             # ISO timestamp or ""
    last_event_ts: str              # ISO timestamp or ""
    runtime_hours: float            # derived from first/last loop_started/stopped events


def _ts_to_dt(ts: str) -> datetime | None:
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return None


def _runtime_hours(events_path: str) -> tuple[float, str, str]:
    """Compute total runtime in hours from loop_started / loop_stopped pairs.

    Also returns (first_event_ts, last_event_ts) for display.
    """
    events = events_tail(events_path, n=100_000)
    if not events:
        return 0.0, "", ""

    first_ts = events[0].get("ts", "")
    last_ts = events[-1].get("ts", "")

    total_seconds = 0.0
    last_start: datetime | None = None
    for e in events:
        evt = e.get("event", "")
        ts = e.get("ts", "")
        dt = _ts_to_dt(ts)
        if dt is None:
            continue
        if evt == "loop_started":
            last_start = dt
        elif evt == "loop_stopped" and last_start is not None:
            delta = (dt - last_start).total_seconds()
            if delta > 0:
                total_seconds += delta
            last_start = None

    # If still running (no final loop_stopped), count to now
    if last_start is not None:
        delta = (datetime.now(timezone.utc) - last_start).total_seconds()
        if delta > 0:
            total_seconds += delta

    return round(total_seconds / 3600, 2), first_ts, last_ts


def compute(state: dict, history_path: str, events_path: str) -> LoopMetrics:
    """Compute all metrics from current state, history, and events."""
    tasks_completed = state.get("tasks_completed", 0)

    # History
    all_entries = history_recent(limit=1_000_000, path=history_path)
    history_entries = len(all_entries)
    success_count = sum(1 for e in all_entries if e.get("success"))
    failure_count = history_entries - success_count
    if history_entries > 0:
        pass_rate = round(success_count / history_entries, 4)
    else:
        pass_rate = -1.0

    # Event counts
    counts = count_by_type(events_path)
    total_events = sum(counts.values())
    tasks_blocked = counts.get("task_blocked", 0)
    cancellation_count = counts.get("claude_cancelled", 0)
    rate_limit_count = counts.get("rate_limit_detected", 0)

    runtime_hours, first_ts, last_ts = _runtime_hours(events_path)

    return LoopMetrics(
        tasks_completed=tasks_completed,
        tasks_blocked=tasks_blocked,
        history_entries=history_entries,
        success_count=success_count,
        failure_count=failure_count,
        validator_pass_rate=pass_rate,
        cancellation_count=cancellation_count,
        rate_limit_count=rate_limit_count,
        event_count=total_events,
        first_event_ts=first_ts,
        last_event_ts=last_ts,
        runtime_hours=runtime_hours,
    )
