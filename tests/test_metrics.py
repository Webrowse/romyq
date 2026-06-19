"""Tests for romyq.metrics — long-run statistics."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from romyq.metrics import LoopMetrics, compute


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso(delta_s: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=delta_s)
    return dt.replace(microsecond=0).isoformat()


def _write_history(path: str, entries: list[dict]) -> None:
    Path(path).write_text(json.dumps(entries), encoding="utf-8")


def _write_events(path: str, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _state(**kwargs) -> dict:
    base = {"tasks_completed": 0, "status": "running"}
    base.update(kwargs)
    return base


# ── LoopMetrics ───────────────────────────────────────────────────────────────

class TestLoopMetrics:
    def test_is_namedtuple(self):
        m = LoopMetrics(
            tasks_completed=0, tasks_blocked=0, history_entries=0,
            success_count=0, failure_count=0, validator_pass_rate=-1.0,
            cancellation_count=0, rate_limit_count=0, event_count=0,
            first_event_ts="", last_event_ts="", runtime_hours=0.0,
        )
        assert m.tasks_completed == 0

    def test_asdict(self):
        m = LoopMetrics(
            tasks_completed=5, tasks_blocked=1, history_entries=10,
            success_count=8, failure_count=2, validator_pass_rate=0.8,
            cancellation_count=0, rate_limit_count=1, event_count=100,
            first_event_ts="2026-01-01T00:00:00+00:00",
            last_event_ts="2026-01-02T00:00:00+00:00",
            runtime_hours=2.5,
        )
        d = m._asdict()
        assert d["tasks_completed"] == 5
        assert d["runtime_hours"] == 2.5


# ── compute() — empty state ───────────────────────────────────────────────────

class TestComputeEmpty:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.h_path = os.path.join(self.tmpdir, "history.json")
        self.e_path = os.path.join(self.tmpdir, "events.log")

    def test_empty_history_and_events(self):
        m = compute(_state(), self.h_path, self.e_path)
        assert m.tasks_completed == 0
        assert m.history_entries == 0
        assert m.validator_pass_rate == -1.0
        assert m.event_count == 0
        assert m.runtime_hours == 0.0

    def test_missing_files_no_crash(self):
        m = compute(_state(), self.h_path, self.e_path)
        assert isinstance(m, LoopMetrics)


# ── compute() — history counting ─────────────────────────────────────────────

class TestComputeHistory:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.h_path = os.path.join(self.tmpdir, "history.json")
        self.e_path = os.path.join(self.tmpdir, "events.log")

    def test_counts_successes_and_failures(self):
        entries = [
            {"task": "t1", "success": True, "timestamp": _now_iso(-100), "mode": "impl", "commit": "a", "validation_reason": "ok"},
            {"task": "t2", "success": True, "timestamp": _now_iso(-90), "mode": "impl", "commit": "b", "validation_reason": "ok"},
            {"task": "t3", "success": False, "timestamp": _now_iso(-80), "mode": "impl", "commit": "", "validation_reason": "fail"},
        ]
        _write_history(self.h_path, entries)
        m = compute(_state(tasks_completed=2), self.h_path, self.e_path)
        assert m.history_entries == 3
        assert m.success_count == 2
        assert m.failure_count == 1
        assert m.tasks_completed == 2

    def test_pass_rate_all_success(self):
        entries = [{"task": "t", "success": True, "timestamp": _now_iso(), "mode": "impl", "commit": "a", "validation_reason": "ok"}]
        _write_history(self.h_path, entries)
        m = compute(_state(), self.h_path, self.e_path)
        assert m.validator_pass_rate == 1.0

    def test_pass_rate_all_failure(self):
        entries = [{"task": "t", "success": False, "timestamp": _now_iso(), "mode": "impl", "commit": "", "validation_reason": "f"}]
        _write_history(self.h_path, entries)
        m = compute(_state(), self.h_path, self.e_path)
        assert m.validator_pass_rate == 0.0

    def test_pass_rate_mixed(self):
        entries = [
            {"task": "t", "success": True, "timestamp": _now_iso(), "mode": "impl", "commit": "a", "validation_reason": "ok"},
            {"task": "t", "success": False, "timestamp": _now_iso(), "mode": "impl", "commit": "", "validation_reason": "fail"},
        ]
        _write_history(self.h_path, entries)
        m = compute(_state(), self.h_path, self.e_path)
        assert m.validator_pass_rate == 0.5


# ── compute() — event counting ────────────────────────────────────────────────

class TestComputeEvents:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.h_path = os.path.join(self.tmpdir, "history.json")
        self.e_path = os.path.join(self.tmpdir, "events.log")

    def test_counts_events_by_type(self):
        _write_events(self.e_path, [
            {"ts": _now_iso(-300), "event": "loop_started"},
            {"ts": _now_iso(-200), "event": "task_blocked"},
            {"ts": _now_iso(-100), "event": "claude_cancelled"},
            {"ts": _now_iso(-50),  "event": "rate_limit_detected"},
            {"ts": _now_iso(-10),  "event": "rate_limit_detected"},
            {"ts": _now_iso(),     "event": "loop_stopped"},
        ])
        m = compute(_state(), self.h_path, self.e_path)
        assert m.event_count == 6
        assert m.tasks_blocked == 1
        assert m.cancellation_count == 1
        assert m.rate_limit_count == 2

    def test_first_and_last_event_ts(self):
        ts1 = "2026-01-01T00:00:00+00:00"
        ts2 = "2026-01-02T12:00:00+00:00"
        _write_events(self.e_path, [
            {"ts": ts1, "event": "loop_started"},
            {"ts": ts2, "event": "loop_stopped"},
        ])
        m = compute(_state(), self.h_path, self.e_path)
        assert m.first_event_ts == ts1
        assert m.last_event_ts == ts2


# ── compute() — runtime hours ─────────────────────────────────────────────────

class TestComputeRuntimeHours:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.h_path = os.path.join(self.tmpdir, "history.json")
        self.e_path = os.path.join(self.tmpdir, "events.log")

    def test_zero_runtime_no_events(self):
        m = compute(_state(), self.h_path, self.e_path)
        assert m.runtime_hours == 0.0

    def test_runtime_from_start_stop_pair(self):
        ts_start = "2026-01-01T00:00:00+00:00"
        ts_stop  = "2026-01-01T02:00:00+00:00"
        _write_events(self.e_path, [
            {"ts": ts_start, "event": "loop_started"},
            {"ts": ts_stop,  "event": "loop_stopped"},
        ])
        m = compute(_state(), self.h_path, self.e_path)
        assert m.runtime_hours == 2.0

    def test_runtime_multiple_sessions(self):
        # Two 1-hour sessions
        _write_events(self.e_path, [
            {"ts": "2026-01-01T00:00:00+00:00", "event": "loop_started"},
            {"ts": "2026-01-01T01:00:00+00:00", "event": "loop_stopped"},
            {"ts": "2026-01-01T10:00:00+00:00", "event": "loop_started"},
            {"ts": "2026-01-01T11:00:00+00:00", "event": "loop_stopped"},
        ])
        m = compute(_state(), self.h_path, self.e_path)
        assert m.runtime_hours == 2.0

    def test_open_session_counts_to_now(self):
        # A loop that started 30 minutes ago with no stop event.
        ts_start = (datetime.now(timezone.utc) - timedelta(minutes=30)).replace(microsecond=0).isoformat()
        _write_events(self.e_path, [
            {"ts": ts_start, "event": "loop_started"},
        ])
        m = compute(_state(), self.h_path, self.e_path)
        # Should be roughly 0.5 hours (allow ±2 minutes for test latency)
        assert 0.45 <= m.runtime_hours <= 0.6
