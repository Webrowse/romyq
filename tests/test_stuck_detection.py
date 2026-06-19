"""Tests for romyq.health_checks — stuck condition detection."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from romyq.health_checks import detect_stuck_conditions


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso(delta_s: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=delta_s)
    return dt.replace(microsecond=0).isoformat()


def _write_history(path: str, entries: list[dict]) -> None:
    import json as _j
    from pathlib import Path
    Path(path).write_text(_j.dumps(entries), encoding="utf-8")


def _write_events(path: str, entries: list[dict]) -> None:
    import json as _j
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(_j.dumps(e) + "\n")


def _state(**kwargs) -> dict:
    base = {
        "phase": "idle",
        "status": "running",
        "heartbeat": _now_iso(),
        "current_task": "",
        "current_task_key": "",
        "current_task_attempts": 0,
        "max_task_attempts": 3,
        "consecutive_failures": 0,
        "paused": False,
        "stop_requested": False,
    }
    base.update(kwargs)
    return base


class TestDetectStuck:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.h_path = os.path.join(self.tmpdir, "history.json")
        self.e_path = os.path.join(self.tmpdir, "events.log")

    def _run(self, state=None, **state_kwargs):
        if state is None:
            state = _state(**state_kwargs)
        return detect_stuck_conditions(
            state=state,
            history_path=self.h_path,
            events_path=self.e_path,
        )

    def test_empty_state_no_warnings(self):
        assert self._run() == []

    # ── Task blocked ──────────────────────────────────────────────────────────

    def test_blocked_task_produces_warning(self):
        warnings = self._run(
            current_task_key="abc123",
            current_task_attempts=3,
            max_task_attempts=3,
        )
        assert any("BLOCKED" in w or "blocked" in w.lower() for w in warnings)

    def test_blocked_task_shows_key(self):
        warnings = self._run(
            current_task_key="abc123def456",
            current_task_attempts=3,
            max_task_attempts=3,
        )
        assert any("abc123" in w for w in warnings)

    def test_not_blocked_no_key_no_warning(self):
        # No key — not blocked even if attempts == ceiling
        warnings = self._run(
            current_task_key="",
            current_task_attempts=3,
            max_task_attempts=3,
        )
        assert not any("BLOCKED" in w for w in warnings)

    def test_below_ceiling_no_blocked_warning(self):
        warnings = self._run(
            current_task_key="abc123",
            current_task_attempts=2,
            max_task_attempts=3,
        )
        assert not any("BLOCKED" in w for w in warnings)

    def test_consecutive_failures_threshold(self):
        warnings = self._run(consecutive_failures=5)
        assert any("consecutive" in w.lower() for w in warnings)

    def test_consecutive_failures_below_threshold(self):
        warnings = self._run(consecutive_failures=4)
        assert not any("consecutive" in w.lower() for w in warnings)

    # ── Repeated validator evidence ───────────────────────────────────────────

    def test_unchanged_evidence_warning(self):
        reason = "tests failed: 3 errors"
        entries = [
            {"task": f"t{i}", "success": False, "timestamp": _now_iso(-i*10),
             "mode": "impl", "commit": "", "validation_reason": reason}
            for i in range(3)
        ]
        _write_history(self.h_path, entries)
        warnings = self._run()
        assert any("unchanged" in w.lower() or "evidence" in w.lower() for w in warnings)

    def test_changed_evidence_no_warning(self):
        entries = [
            {"task": "t1", "success": False, "timestamp": _now_iso(-30),
             "mode": "impl", "commit": "", "validation_reason": "reason A"},
            {"task": "t2", "success": False, "timestamp": _now_iso(-20),
             "mode": "impl", "commit": "", "validation_reason": "reason B"},
            {"task": "t3", "success": False, "timestamp": _now_iso(-10),
             "mode": "impl", "commit": "", "validation_reason": "reason C"},
        ]
        _write_history(self.h_path, entries)
        warnings = self._run()
        assert not any("unchanged" in w.lower() for w in warnings)

    def test_only_two_same_failures_no_warning(self):
        reason = "same error"
        entries = [
            {"task": f"t{i}", "success": False, "timestamp": _now_iso(-i*10),
             "mode": "impl", "commit": "", "validation_reason": reason}
            for i in range(2)
        ]
        _write_history(self.h_path, entries)
        warnings = self._run()
        assert not any("unchanged" in w.lower() for w in warnings)

    # ── No successful task for 2 hours ────────────────────────────────────────

    def test_drought_warning_after_two_hours(self):
        last_success_ts = _now_iso(-7300)  # > 2 hours ago
        entries = [
            {"task": "s", "success": True, "timestamp": last_success_ts,
             "mode": "impl", "commit": "a", "validation_reason": "ok"},
            {"task": "f", "success": False, "timestamp": _now_iso(-100),
             "mode": "impl", "commit": "", "validation_reason": "fail"},
        ]
        _write_history(self.h_path, entries)
        warnings = self._run()
        assert any("hour" in w.lower() or "successful" in w.lower() for w in warnings)

    def test_no_drought_warning_within_two_hours(self):
        entries = [
            {"task": "s", "success": True, "timestamp": _now_iso(-3600),
             "mode": "impl", "commit": "a", "validation_reason": "ok"},
        ]
        _write_history(self.h_path, entries)
        warnings = self._run()
        assert not any("hour" in w.lower() and "successful" in w.lower() for w in warnings)

    # ── Stale heartbeat ───────────────────────────────────────────────────────

    def test_stale_heartbeat_active_phase(self):
        warnings = detect_stuck_conditions(
            state=_state(phase="executing"),
            history_path=self.h_path,
            events_path=self.e_path,
            heartbeat_age_s=1900,
        )
        assert any("heartbeat" in w.lower() or "stuck" in w.lower() for w in warnings)

    def test_fresh_heartbeat_no_warning(self):
        warnings = detect_stuck_conditions(
            state=_state(phase="executing"),
            history_path=self.h_path,
            events_path=self.e_path,
            heartbeat_age_s=30,
        )
        assert not any("heartbeat" in w.lower() for w in warnings)

    def test_stale_heartbeat_idle_phase_no_warning(self):
        # Stale heartbeat only warned for active phases
        warnings = detect_stuck_conditions(
            state=_state(phase="idle"),
            history_path=self.h_path,
            events_path=self.e_path,
            heartbeat_age_s=9999,
        )
        assert not any("heartbeat" in w.lower() for w in warnings)

    # ── Rate-limit storm ──────────────────────────────────────────────────────

    def test_rate_limit_storm_warning(self):
        events = [
            {"ts": _now_iso(-i*10), "event": "rate_limit_detected"}
            for i in range(5)
        ]
        _write_events(self.e_path, events)
        warnings = self._run()
        assert any("rate" in w.lower() for w in warnings)

    def test_few_rate_limits_no_storm_warning(self):
        events = [
            {"ts": _now_iso(-i*10), "event": "rate_limit_detected"}
            for i in range(2)
        ]
        _write_events(self.e_path, events)
        warnings = self._run()
        assert not any("storm" in w.lower() or "token" in w.lower() for w in warnings)

    # ── Return type ───────────────────────────────────────────────────────────

    def test_returns_list_always(self):
        result = self._run()
        assert isinstance(result, list)

    def test_warnings_are_strings(self):
        _write_events(self.e_path, [
            {"ts": _now_iso(-i), "event": "rate_limit_detected"} for i in range(5)
        ])
        warnings = self._run(
            current_task_key="k1",
            current_task_attempts=3,
            max_task_attempts=3,
        )
        for w in warnings:
            assert isinstance(w, str)
