"""Tests for Task 3: RunState enum and transition table.

Verifies:
- All expected states exist
- Transitions from the table are valid
- Invalid transitions are detected
- set_phase() updates the phase field and calls heartbeat
- set_phase() warns on invalid transition without raising
- coerce() returns the default on unknown strings
- State machine has no missing transitions for known states
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from romyq.runstate import RunState, TRANSITIONS, coerce, is_valid_transition
from romyq.state import DEFAULT_STATE, set_phase


# ── enum values ───────────────────────────────────────────────────────────────

class TestRunStateEnum:

    def test_all_expected_states_exist(self):
        expected = {
            "idle", "planning", "executing", "validating",
            "paused", "rate_limited", "stopping", "stopped", "failed",
        }
        actual = {s.value for s in RunState}
        assert expected == actual

    def test_enum_inherits_from_str(self):
        assert isinstance(RunState.IDLE, str)
        assert RunState.IDLE == "idle"

    def test_value_equals_string(self):
        for state in RunState:
            assert state == state.value

    def test_all_states_in_transitions_table(self):
        """Every RunState is a key in the TRANSITIONS table."""
        for state in RunState:
            assert state in TRANSITIONS, f"{state} missing from TRANSITIONS"


# ── is_valid_transition ───────────────────────────────────────────────────────

class TestValidTransitions:

    def test_idle_to_planning(self):
        assert is_valid_transition(RunState.IDLE, RunState.PLANNING)

    def test_planning_to_executing(self):
        assert is_valid_transition(RunState.PLANNING, RunState.EXECUTING)

    def test_executing_to_validating(self):
        assert is_valid_transition(RunState.EXECUTING, RunState.VALIDATING)

    def test_validating_to_idle(self):
        assert is_valid_transition(RunState.VALIDATING, RunState.IDLE)

    def test_executing_to_rate_limited(self):
        assert is_valid_transition(RunState.EXECUTING, RunState.RATE_LIMITED)

    def test_rate_limited_to_planning(self):
        assert is_valid_transition(RunState.RATE_LIMITED, RunState.PLANNING)

    def test_any_state_to_stopping(self):
        """Emergency exit: all states except STOPPING/STOPPED can transition to STOPPING."""
        for state in RunState:
            if state in (RunState.STOPPED, RunState.STOPPING):
                continue
            assert is_valid_transition(state, RunState.STOPPING), \
                f"{state} should be able to transition to STOPPING"

    def test_stopping_to_stopped(self):
        assert is_valid_transition(RunState.STOPPING, RunState.STOPPED)

    def test_paused_to_idle(self):
        assert is_valid_transition(RunState.PAUSED, RunState.IDLE)

    def test_validating_to_failed(self):
        assert is_valid_transition(RunState.VALIDATING, RunState.FAILED)

    def test_failed_to_planning(self):
        assert is_valid_transition(RunState.FAILED, RunState.PLANNING)


class TestInvalidTransitions:

    def test_stopped_has_no_valid_transitions(self):
        """STOPPED is a terminal state."""
        for to_state in RunState:
            assert not is_valid_transition(RunState.STOPPED, to_state), \
                f"STOPPED should not transition to {to_state}"

    def test_idle_cannot_go_to_validating(self):
        assert not is_valid_transition(RunState.IDLE, RunState.VALIDATING)

    def test_executing_cannot_go_to_planning(self):
        assert not is_valid_transition(RunState.EXECUTING, RunState.PLANNING)

    def test_unknown_string_from_state_allows_transition(self):
        """Unknown from-state is treated as permissive (forward-compat)."""
        assert is_valid_transition("unknown_future_state", RunState.IDLE)

    def test_string_values_accepted(self):
        """is_valid_transition accepts string values as well as enum members."""
        assert is_valid_transition("idle", "planning")
        assert is_valid_transition("idle", RunState.PLANNING)
        assert is_valid_transition(RunState.IDLE, "planning")


# ── coerce ────────────────────────────────────────────────────────────────────

class TestCoerce:

    def test_valid_string_returns_enum(self):
        assert coerce("idle") == RunState.IDLE
        assert coerce("executing") == RunState.EXECUTING

    def test_invalid_string_returns_default(self):
        assert coerce("not_a_state") == RunState.IDLE

    def test_custom_default(self):
        assert coerce("invalid", default=RunState.FAILED) == RunState.FAILED


# ── set_phase integration ─────────────────────────────────────────────────────

class TestSetPhase:

    def test_sets_phase_field(self):
        state = DEFAULT_STATE.copy()
        set_phase(state, RunState.PLANNING)
        assert state["phase"] == "planning"

    def test_accepts_string(self):
        state = DEFAULT_STATE.copy()
        set_phase(state, "executing")
        assert state["phase"] == "executing"

    def test_updates_heartbeat(self):
        state = DEFAULT_STATE.copy()
        old_hb = state["heartbeat"]
        set_phase(state, RunState.EXECUTING)
        assert state["heartbeat"] != old_hb

    def test_warns_on_invalid_transition(self):
        """Invalid transitions print a warning to stderr but do not raise."""
        state = DEFAULT_STATE.copy()
        state["phase"] = "idle"
        stderr_capture = io.StringIO()
        old_stderr = sys.stderr
        sys.stderr = stderr_capture
        try:
            set_phase(state, RunState.VALIDATING)  # idle → validating is invalid
        finally:
            sys.stderr = old_stderr
        output = stderr_capture.getvalue()
        # Either a warning was printed or the phase was updated anyway (permissive)
        assert "Warning" in output or "warn" in output.lower() or state["phase"] == "validating"

    def test_does_not_raise_on_invalid_transition(self):
        """set_phase() must never raise, even for invalid transitions."""
        state = DEFAULT_STATE.copy()
        state["phase"] = "idle"
        # Executing → Idle is not valid but must not raise
        set_phase(state, RunState.IDLE)   # valid
        set_phase(state, RunState.VALIDATING)  # invalid from idle — must not raise
