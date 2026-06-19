"""Tests for romyq.recovery — resume intelligence."""
import pytest
from romyq.recovery import RecoveryState, analyze_recovery_state


# ── helpers ───────────────────────────────────────────────────────────────────

def _state(**kwargs) -> dict:
    base = {
        "phase": "idle",
        "status": "running",
        "heartbeat": "",
        "current_task": "",
        "current_task_key": "",
        "current_task_attempts": 0,
        "max_task_attempts": 3,
        "consecutive_failures": 0,
        "paused": False,
        "stop_requested": False,
        "resume_at": "",
    }
    base.update(kwargs)
    return base


# ── RecoveryState ─────────────────────────────────────────────────────────────

class TestRecoveryState:
    def test_is_namedtuple(self):
        rs = RecoveryState(situation="s", recommendation="r", severity="ok")
        assert rs.situation == "s"
        assert rs.recommendation == "r"
        assert rs.severity == "ok"

    def test_severity_values(self):
        for sev in ("ok", "warning", "error"):
            rs = RecoveryState("s", "r", sev)
            assert rs.severity == sev


# ── analyze_recovery_state ────────────────────────────────────────────────────

class TestAnalyzeRecoveryState:
    def test_idle_phase_is_ok(self):
        rs = analyze_recovery_state(_state(phase="idle"))
        assert rs.severity == "ok"

    def test_stopped_phase_is_ok(self):
        rs = analyze_recovery_state(_state(phase="stopped"))
        assert rs.severity == "ok"

    def test_paused_phase_is_ok(self):
        rs = analyze_recovery_state(_state(phase="paused", paused=True))
        assert rs.severity == "ok"

    def test_executing_phase_is_warning(self):
        rs = analyze_recovery_state(_state(phase="executing"))
        assert rs.severity == "warning"
        assert "executing" in rs.situation.lower()

    def test_validating_phase_is_warning(self):
        rs = analyze_recovery_state(_state(phase="validating"))
        assert rs.severity == "warning"

    def test_planning_phase_is_warning(self):
        rs = analyze_recovery_state(_state(phase="planning"))
        assert rs.severity == "warning"

    def test_failed_phase_is_error(self):
        rs = analyze_recovery_state(_state(phase="failed"))
        assert rs.severity == "error"

    def test_rate_limited_phase_is_warning(self):
        rs = analyze_recovery_state(_state(phase="rate_limited"))
        assert rs.severity == "warning"

    def test_stop_requested_flag_overrides_phase(self):
        rs = analyze_recovery_state(_state(phase="executing", stop_requested=True))
        assert rs.severity == "warning"
        assert "stop" in rs.situation.lower()

    def test_paused_mismatch_overrides_phase(self):
        # paused=True but phase=executing — mismatch
        rs = analyze_recovery_state(_state(phase="executing", paused=True))
        assert rs.severity == "warning"

    def test_blocked_task_is_error(self):
        rs = analyze_recovery_state(_state(
            phase="idle",
            current_task_key="abc123",
            current_task_attempts=3,
            max_task_attempts=3,
        ))
        assert rs.severity == "error"
        assert "BLOCKED" in rs.situation or "blocked" in rs.situation.lower()

    def test_blocked_shows_attempt_count(self):
        rs = analyze_recovery_state(_state(
            phase="idle",
            current_task_key="abc123",
            current_task_attempts=5,
            max_task_attempts=3,
        ))
        assert "5" in rs.situation or "5/3" in rs.situation

    def test_stale_heartbeat_active_phase(self):
        rs = analyze_recovery_state(
            _state(phase="executing"),
            heartbeat_age_s=2000,
        )
        assert rs.severity == "error"
        assert "heartbeat" in rs.situation.lower() or "minutes" in rs.situation.lower()

    def test_fresh_heartbeat_active_phase_is_warning_not_error(self):
        rs = analyze_recovery_state(
            _state(phase="executing"),
            heartbeat_age_s=30,
        )
        # Fresh heartbeat: no stale-heartbeat error, just normal phase warning
        assert rs.severity == "warning"

    def test_consecutive_failures_error(self):
        rs = analyze_recovery_state(_state(consecutive_failures=7))
        assert rs.severity == "error"
        assert "7" in rs.situation

    def test_consecutive_failures_below_threshold_uses_phase(self):
        rs = analyze_recovery_state(_state(phase="idle", consecutive_failures=2))
        assert rs.severity == "ok"

    def test_task_preview_in_situation_for_active_phase(self):
        rs = analyze_recovery_state(_state(
            phase="executing",
            current_task="Add user authentication module",
        ))
        assert "Add user authentication module" in rs.situation

    def test_unknown_phase_is_warning(self):
        rs = analyze_recovery_state(_state(phase="zap_unknown_xyz"))
        assert rs.severity == "warning"

    def test_returns_named_tuple_always(self):
        for phase in ("idle", "planning", "executing", "validating",
                      "paused", "stopped", "failed", "rate_limited", "stopping"):
            rs = analyze_recovery_state(_state(phase=phase))
            assert isinstance(rs, RecoveryState)

    def test_recommendation_is_non_empty(self):
        for phase in ("idle", "executing", "failed"):
            rs = analyze_recovery_state(_state(phase=phase))
            assert rs.recommendation.strip()
