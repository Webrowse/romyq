"""Tests for Task 2: Persistent failure tracking.

Verifies:
- record_task_failure() increments per-task and consecutive counters
- record_task_success() resets all failure tracking
- is_task_blocked() respects max_task_attempts (default 3)
- Counters persist across load/save cycles (survive restarts)
- is_task_blocked() matches by task_key, not just count
- max_task_attempts is configurable in state
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq.state import (
    DEFAULT_STATE,
    is_task_blocked,
    load as load_state,
    record_task_failure,
    record_task_success,
    save as save_state,
)


@pytest.fixture
def state(tmp_path: Path) -> dict:
    s = DEFAULT_STATE.copy()
    sf = tmp_path / "state.json"
    save_state(s, str(sf))
    return s


@pytest.fixture
def state_path(tmp_path: Path) -> str:
    sf = tmp_path / "state.json"
    s = DEFAULT_STATE.copy()
    save_state(s, str(sf))
    return str(sf)


# ── record_task_failure ───────────────────────────────────────────────────────

class TestRecordTaskFailure:

    def test_first_failure_sets_key_and_attempts(self, state):
        record_task_failure(state, "abc123", "Claude timed out")
        assert state["current_task_key"] == "abc123"
        assert state["current_task_attempts"] == 1
        assert state["last_failure_reason"] == "Claude timed out"

    def test_same_key_increments_attempts(self, state):
        record_task_failure(state, "abc123", "error 1")
        record_task_failure(state, "abc123", "error 2")
        assert state["current_task_attempts"] == 2
        assert state["last_failure_reason"] == "error 2"

    def test_new_key_resets_per_task_counter(self, state):
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "xyz789", "different error")
        assert state["current_task_key"] == "xyz789"
        assert state["current_task_attempts"] == 1

    def test_always_increments_consecutive_failures(self, state):
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "xyz789", "error")  # different task
        assert state["consecutive_failures"] == 2

    def test_sets_failure_timestamp(self, state):
        record_task_failure(state, "abc123", "error")
        assert state["last_failure_timestamp"]
        assert "T" in state["last_failure_timestamp"]  # ISO format

    def test_failure_reason_stored(self, state):
        record_task_failure(state, "key1", "No new commit created")
        assert state["last_failure_reason"] == "No new commit created"


# ── record_task_success ───────────────────────────────────────────────────────

class TestRecordTaskSuccess:

    def test_resets_task_key(self, state):
        record_task_failure(state, "abc123", "error")
        record_task_success(state)
        assert state["current_task_key"] == ""

    def test_resets_attempts(self, state):
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        record_task_success(state)
        assert state["current_task_attempts"] == 0

    def test_resets_failure_reason(self, state):
        record_task_failure(state, "abc123", "some reason")
        record_task_success(state)
        assert state["last_failure_reason"] == ""

    def test_resets_consecutive_failures(self, state):
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "xyz789", "error")
        record_task_success(state)
        assert state["consecutive_failures"] == 0


# ── is_task_blocked ───────────────────────────────────────────────────────────

class TestIsTaskBlocked:

    def test_not_blocked_by_default(self, state):
        assert is_task_blocked(state, "abc123") is False

    def test_not_blocked_below_ceiling(self, state):
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        assert is_task_blocked(state, "abc123") is False

    def test_blocked_at_ceiling(self, state):
        state["max_task_attempts"] = 3
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        assert is_task_blocked(state, "abc123") is True

    def test_blocked_above_ceiling(self, state):
        state["max_task_attempts"] = 2
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        assert is_task_blocked(state, "abc123") is True

    def test_not_blocked_for_different_key(self, state):
        state["max_task_attempts"] = 1
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        # Different key — not blocked even though count > ceiling
        assert is_task_blocked(state, "xyz789") is False

    def test_configurable_ceiling_1(self, state):
        state["max_task_attempts"] = 1
        record_task_failure(state, "abc123", "error")
        assert is_task_blocked(state, "abc123") is True

    def test_configurable_ceiling_5(self, state):
        state["max_task_attempts"] = 5
        for _ in range(4):
            record_task_failure(state, "abc123", "error")
        assert is_task_blocked(state, "abc123") is False
        record_task_failure(state, "abc123", "error")
        assert is_task_blocked(state, "abc123") is True

    def test_success_clears_block(self, state):
        state["max_task_attempts"] = 2
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        assert is_task_blocked(state, "abc123") is True
        record_task_success(state)
        assert is_task_blocked(state, "abc123") is False


# ── persistence across restarts ───────────────────────────────────────────────

class TestFailureTrackingPersistence:

    def test_failure_count_survives_restart(self, state_path):
        """Failure counters persist after save/load (survives restart)."""
        state = load_state(state_path)
        record_task_failure(state, "abc123", "timeout")
        record_task_failure(state, "abc123", "timeout")
        save_state(state, state_path)

        # Simulate restart: load fresh
        reloaded = load_state(state_path)
        assert reloaded["current_task_key"] == "abc123"
        assert reloaded["current_task_attempts"] == 2
        assert reloaded["last_failure_reason"] == "timeout"

    def test_is_task_blocked_after_restart(self, state_path):
        """is_task_blocked() returns True after restart if attempts >= ceiling."""
        state = load_state(state_path)
        state["max_task_attempts"] = 3
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        save_state(state, state_path)

        reloaded = load_state(state_path)
        assert is_task_blocked(reloaded, "abc123") is True

    def test_success_persisted_clears_block(self, state_path):
        """record_task_success persisted → block is cleared after restart."""
        state = load_state(state_path)
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        record_task_failure(state, "abc123", "error")
        record_task_success(state)
        save_state(state, state_path)

        reloaded = load_state(state_path)
        assert is_task_blocked(reloaded, "abc123") is False

    def test_consecutive_failures_persist(self, state_path):
        """consecutive_failures counter persists across save/load."""
        state = load_state(state_path)
        record_task_failure(state, "key1", "error")
        record_task_failure(state, "key2", "error")
        save_state(state, state_path)

        reloaded = load_state(state_path)
        assert reloaded["consecutive_failures"] == 2

    def test_new_install_defaults_are_zero(self, tmp_path):
        """Fresh state.json (new install) has zero failure counts."""
        sf = tmp_path / "state.json"
        state = load_state(str(sf))  # creates new file
        assert state["current_task_key"] == ""
        assert state["current_task_attempts"] == 0
        assert state["consecutive_failures"] == 0
        assert state["max_task_attempts"] == 3
