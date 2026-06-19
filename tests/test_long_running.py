"""7-day reliability simulation — validates system behaviour across extended runs.

These tests simulate conditions seen in multi-day autonomous execution:
- Multiple loop restart cycles
- Mixed success/failure patterns
- Rate-limit storms
- Heartbeat staleness and crash recovery
- Blocked-task accumulation and clearance
- Context regeneration
- Stats consistency across restarts
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from romyq.events import count_by_type, emit
from romyq.health_checks import detect_stuck_conditions
from romyq.history import add_entry, recent
from romyq.metrics import compute as compute_metrics
from romyq.recovery import analyze_recovery_state
from romyq.state import (
    DEFAULT_STATE,
    load as load_state,
    record_task_failure,
    record_task_success,
    save as save_state,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso(delta_s: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=delta_s)
    return dt.replace(microsecond=0).isoformat()


def _fresh_state(tmp_path: Path) -> tuple[str, str, str, str]:
    """Create a clean workspace with all paths. Returns (s_path, h_path, f_path, e_path)."""
    d = tmp_path / ".romyq"
    d.mkdir(exist_ok=True)
    s_path = str(d / "state.json")
    h_path = str(d / "history.json")
    f_path = str(d / "findings.json")
    e_path = str(d / "events.log")
    state = dict(DEFAULT_STATE)
    save_state(state, s_path)
    Path(h_path).write_text(json.dumps([]), encoding="utf-8")
    Path(f_path).write_text(json.dumps([]), encoding="utf-8")
    return s_path, h_path, f_path, e_path


def _simulate_task(
    s_path: str, h_path: str, e_path: str,
    key: str, success: bool, reason: str = "ok",
    ts: str | None = None,
) -> None:
    """Simulate a single task execution cycle (no real Claude)."""
    state = load_state(s_path)
    state["heartbeat"] = ts or _now_iso()
    state["current_task"] = f"task {key}"
    if success:
        record_task_success(state)
        state["tasks_completed"] = state.get("tasks_completed", 0) + 1
        emit(e_path, "task_completed", key=key)
        add_entry(
            task=f"task {key}", mode="impl", success=True,
            commit="abc1234", validation_reason=reason, path=h_path,
        )
    else:
        record_task_failure(state, key, reason)
        emit(e_path, "validator_failed", key=key, reason=reason)
        add_entry(
            task=f"task {key}", mode="impl", success=False,
            commit="", validation_reason=reason, path=h_path,
        )
    save_state(state, s_path)


# ── Multi-day restart resilience ──────────────────────────────────────────────

class TestMultiDayRestartResilience:
    """Simulate 7 sessions of 20 tasks each (140 total), with crashes between sessions."""

    def test_state_survives_seven_restarts(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)
        sessions = 7
        tasks_per_session = 20

        for session in range(sessions):
            emit(e_path, "loop_started")
            for t in range(tasks_per_session):
                key = f"s{session}t{t}"
                success = (t % 4 != 0)  # 75% success rate
                _simulate_task(s_path, h_path, e_path, key, success)
            emit(e_path, "loop_stopped", reason="stop_requested")

        state = load_state(s_path)
        # 75% of 140 tasks succeed
        assert state["tasks_completed"] >= 100

        m = compute_metrics(state, h_path, e_path)
        assert m.history_entries == tasks_per_session * sessions
        assert m.runtime_hours >= 0.0  # runtime requires start/stop events
        assert abs(m.validator_pass_rate - 0.75) < 0.02

    def test_metrics_consistent_after_restart(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)

        # Session 1
        emit(e_path, "loop_started")
        for i in range(10):
            _simulate_task(s_path, h_path, e_path, f"a{i}", success=True)
        emit(e_path, "loop_stopped", reason="stop_requested")

        state1 = load_state(s_path)
        m1 = compute_metrics(state1, h_path, e_path)

        # Session 2 — same workspace, new loop
        emit(e_path, "loop_started")
        for i in range(10):
            _simulate_task(s_path, h_path, e_path, f"b{i}", success=False)
        emit(e_path, "loop_stopped", reason="stop_requested")

        state2 = load_state(s_path)
        m2 = compute_metrics(state2, h_path, e_path)

        assert m2.history_entries == 20
        assert m2.success_count == 10
        assert m2.failure_count == 10
        assert m2.validator_pass_rate == 0.5


# ── Progressive failure accumulation ─────────────────────────────────────────

class TestProgressiveFailureAccumulation:
    def test_stuck_detection_triggers_after_drought(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)

        # Simulate success 3 hours ago, then only failures
        old_ts = _now_iso(-3 * 3600 - 60)
        _simulate_task(s_path, h_path, e_path, "s1", success=True, ts=old_ts)
        for i in range(5):
            _simulate_task(s_path, h_path, e_path, f"f{i}", success=False,
                           reason="tests fail")

        state = load_state(s_path)
        warnings = detect_stuck_conditions(state, h_path, e_path)
        assert any("hour" in w.lower() or "successful" in w.lower() for w in warnings)

    def test_consecutive_failure_warning_at_threshold(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)

        for i in range(5):
            _simulate_task(s_path, h_path, e_path, f"f{i}", success=False, reason="fail")

        state = load_state(s_path)
        warnings = detect_stuck_conditions(state, h_path, e_path)
        assert any("consecutive" in w.lower() for w in warnings)

    def test_success_clears_consecutive_failures(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)

        for i in range(5):
            _simulate_task(s_path, h_path, e_path, f"f{i}", success=False, reason="fail")

        # One success clears the streak
        _simulate_task(s_path, h_path, e_path, "ok1", success=True)

        state = load_state(s_path)
        assert state.get("consecutive_failures", 0) == 0

    def test_repeated_evidence_warning(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)
        reason = "SyntaxError in module.py line 42"
        for i in range(4):
            _simulate_task(s_path, h_path, e_path, f"f{i}", success=False, reason=reason)
        state = load_state(s_path)
        warnings = detect_stuck_conditions(state, h_path, e_path)
        assert any("unchanged" in w.lower() or "evidence" in w.lower() for w in warnings)


# ── Rate-limit storm ──────────────────────────────────────────────────────────

class TestRateLimitStorm:
    def test_rate_limit_storm_detected(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)

        # Simulate 5 rate-limit events in recent history
        for _ in range(5):
            emit(e_path, "rate_limit_detected")

        state = load_state(s_path)
        warnings = detect_stuck_conditions(state, h_path, e_path)
        assert any("rate" in w.lower() for w in warnings)

    def test_rate_limit_count_in_metrics(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)

        for _ in range(3):
            emit(e_path, "rate_limit_detected")
        emit(e_path, "rate_limit_recovered")

        state = load_state(s_path)
        m = compute_metrics(state, h_path, e_path)
        assert m.rate_limit_count == 3


# ── Crash recovery analysis ───────────────────────────────────────────────────

class TestCrashRecoveryAnalysis:
    def test_stale_heartbeat_crash_detected(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)
        state = load_state(s_path)
        state["phase"] = "executing"
        state["heartbeat"] = _now_iso(-3600)
        save_state(state, s_path)

        state = load_state(s_path)
        recovery = analyze_recovery_state(state)
        # Either stale heartbeat error or executing-phase warning
        assert recovery.severity in ("warning", "error")

    def test_stopped_phase_is_ok(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)
        state = load_state(s_path)
        state["phase"] = "stopped"
        save_state(state, s_path)

        state = load_state(s_path)
        recovery = analyze_recovery_state(state)
        assert recovery.severity == "ok"

    def test_failed_state_error_severity(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)
        state = load_state(s_path)
        state["phase"] = "failed"
        state["consecutive_failures"] = 10
        save_state(state, s_path)

        state = load_state(s_path)
        recovery = analyze_recovery_state(state)
        assert recovery.severity == "error"

    def test_recovery_recommendation_not_empty(self, tmp_path):
        for phase in ("idle", "executing", "failed", "stopped", "paused"):
            tmp = tempfile.mkdtemp()
            tp = Path(tmp)
            s_path, _, _, _ = _fresh_state(tp)
            state = load_state(s_path)
            state["phase"] = phase
            save_state(state, s_path)
            state = load_state(s_path)
            r = analyze_recovery_state(state)
            assert r.recommendation.strip(), f"Empty recommendation for phase={phase}"


# ── Context generation and persistence ───────────────────────────────────────

class TestContextGenerationPersistence:
    def test_context_survives_write_read_cycle(self, tmp_path):
        from romyq.context import load, write
        path = write(str(tmp_path))
        content = load(str(tmp_path))
        assert "# Repository Context" in content

    def test_context_regeneration_overwrites(self, tmp_path):
        from romyq.context import write
        path1 = write(str(tmp_path))
        path2 = write(str(tmp_path))
        assert path1 == path2
        content = Path(path2).read_text(encoding="utf-8")
        assert "# Repository Context" in content

    def test_load_returns_empty_without_write(self, tmp_path):
        from romyq.context import load
        assert load(str(tmp_path)) == ""


# ── Stats accumulation over long run ─────────────────────────────────────────

class TestStatsAccumulation:
    def test_runtime_accumulates_across_sessions(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)

        # Two 1-hour sessions
        for i in range(2):
            start = (datetime.now(timezone.utc) - timedelta(hours=2 - i)).replace(microsecond=0).isoformat()
            stop = (datetime.now(timezone.utc) - timedelta(hours=1 - i)).replace(microsecond=0).isoformat()
            with open(e_path, "a") as f:
                f.write(json.dumps({"ts": start, "event": "loop_started"}) + "\n")
                f.write(json.dumps({"ts": stop, "event": "loop_stopped"}) + "\n")

        state = load_state(s_path)
        m = compute_metrics(state, h_path, e_path)
        assert m.runtime_hours >= 1.9

    def test_cancellation_count_increments(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)

        for _ in range(3):
            emit(e_path, "claude_cancelled")

        state = load_state(s_path)
        m = compute_metrics(state, h_path, e_path)
        assert m.cancellation_count == 3

    def test_tasks_blocked_count(self, tmp_path):
        s_path, h_path, f_path, e_path = _fresh_state(tmp_path)

        for i in range(4):
            emit(e_path, "task_blocked", key=f"k{i}")

        state = load_state(s_path)
        m = compute_metrics(state, h_path, e_path)
        assert m.tasks_blocked == 4
