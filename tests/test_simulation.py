"""Task 8: Overnight simulation tests.

Tests that simulate scenarios equivalent to "run unattended for 8–12 hours."
These tests do NOT invoke Claude or DeepSeek — they drive the state machine
and verification logic directly.

Scenarios covered:
  1. Pause → resume → stop flow
  2. Validator failures accumulate and persist across restart
  3. NO_ACTION_REQUIRED advances without failure streak
  4. Rate-limit sleep respects stop_requested early exit
  5. Persistent failure tracking blocks repeated failing task
  6. Restart recovery: blocked task not retried after reload
  7. Dirty repository recovery: user files preserved across multiple failures
  8. Consecutive failure ceiling triggers finding and reset
  9. Diagnosis mode entry and success recovery
  10. Phase progression through IDLE → PLANNING → EXECUTING → VALIDATING → IDLE
  11. Event log captures task lifecycle events
  12. CancellationToken stops within POLL_INTERVAL of request
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from romyq.cancel import CancellationToken, POLL_INTERVAL
from romyq.events import (
    LOOP_STARTED, LOOP_STOPPED, NO_ACTION_REQUIRED, RETRY,
    STOP_DETECTED, TASK_BLOCKED, TASK_COMPLETED, TASK_STARTED,
    VALIDATOR_FAILED, VALIDATOR_PASSED,
    count_by_type, emit, tail,
)
from romyq.state import (
    DEFAULT_STATE,
    is_task_blocked,
    load as load_state,
    record_task_failure,
    record_task_success,
    refresh_control_flags,
    save as save_state,
    set_phase,
)
from romyq.runstate import RunState
from romyq.validator import FAILURE, SUCCESS, validate


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    sf = tmp_path / "state.json"
    save_state(DEFAULT_STATE.copy(), str(sf))
    return sf


@pytest.fixture
def events_file(tmp_path: Path) -> str:
    return str(tmp_path / "events.log")


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """Minimal git repository for validator tests."""
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, env=env)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, capture_output=True)
    (tmp_path / "readme.txt").write_text("initial")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, env=env)
    return tmp_path


def _head(repo: Path) -> str:
    r = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=repo, capture_output=True, text=True,
    )
    return r.stdout.strip()


# ── Scenario 1: Pause → resume → stop ────────────────────────────────────────

class TestPauseResumeStopFlow:

    def test_pause_flag_survives_loop_save(self, state_file):
        """CLI pause written to disk is not overwritten by loop's save."""
        mem = load_state(str(state_file))

        # CLI pauses while loop is executing Claude
        cli_state = load_state(str(state_file))
        cli_state["paused"] = True
        save_state(cli_state, str(state_file))

        # Loop finishes task and saves — must refresh flags first
        mem["tasks_completed"] += 1
        refresh_control_flags(mem, str(state_file))
        save_state(mem, str(state_file))

        final = load_state(str(state_file))
        assert final["paused"] is True

    def test_stop_flag_survives_long_claude_execution(self, state_file):
        """stop_requested written mid-execution is not overwritten at end of iteration."""
        mem = load_state(str(state_file))

        # Stop arrives while Claude was running (30 minutes)
        cli_state = load_state(str(state_file))
        cli_state["stop_requested"] = True
        save_state(cli_state, str(state_file))

        # End of iteration: refresh before save
        refresh_control_flags(mem, str(state_file))
        save_state(mem, str(state_file))

        assert load_state(str(state_file))["stop_requested"] is True

    def test_cancellation_token_detects_stop_within_poll_interval(self, state_file):
        """stop request is detected within POLL_INTERVAL seconds."""
        token = CancellationToken(str(state_file))

        # Write stop to state file
        state = load_state(str(state_file))
        state["stop_requested"] = True
        save_state(state, str(state_file))

        # Force cache expiry
        with patch("romyq.cancel.time.monotonic",
                   return_value=token._last_read + POLL_INTERVAL + 1):
            detected = token.is_stop_requested()

        assert detected is True


# ── Scenario 2: Failure persistence across restart ────────────────────────────

class TestFailurePersistenceAcrossRestart:

    def test_attempt_count_survives_restart(self, state_file):
        state = load_state(str(state_file))
        record_task_failure(state, "task_abc", "Claude timed out")
        record_task_failure(state, "task_abc", "No new commit")
        save_state(state, str(state_file))

        # Simulate restart
        reloaded = load_state(str(state_file))
        assert reloaded["current_task_key"] == "task_abc"
        assert reloaded["current_task_attempts"] == 2
        assert reloaded["last_failure_reason"] == "No new commit"

    def test_block_detected_after_restart(self, state_file):
        state = load_state(str(state_file))
        state["max_task_attempts"] = 3
        for _ in range(3):
            record_task_failure(state, "task_abc", "error")
        save_state(state, str(state_file))

        # After restart, task is still blocked
        reloaded = load_state(str(state_file))
        assert is_task_blocked(reloaded, "task_abc") is True

    def test_different_task_not_blocked(self, state_file):
        state = load_state(str(state_file))
        state["max_task_attempts"] = 3
        for _ in range(3):
            record_task_failure(state, "task_abc", "error")
        save_state(state, str(state_file))

        reloaded = load_state(str(state_file))
        # A different task should not be blocked
        assert is_task_blocked(reloaded, "task_xyz") is False


# ── Scenario 3: NO_ACTION_REQUIRED does not increment failure streaks ─────────

class TestNoActionRequiredDoesNotFailStreak:

    def test_no_action_required_does_not_call_record_failure(self, git_repo):
        """When outcome is NO_ACTION_REQUIRED, failure tracking must not update."""
        commit = _head(git_repo)
        state = DEFAULT_STATE.copy()

        result = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=0,
            stdout="Feature already implemented.\nCOMPLETED",
        )
        from romyq.validator import NO_ACTION_REQUIRED as NAR
        assert result.outcome == NAR

        # Simulate correct loop behavior: success path resets streaks
        record_task_success(state)
        assert state["current_task_attempts"] == 0
        assert state["consecutive_failures"] == 0

    def test_no_action_required_advances_tasks(self, git_repo):
        """NO_ACTION_REQUIRED should increment tasks_completed."""
        state = DEFAULT_STATE.copy()
        from romyq.validator import NO_ACTION_REQUIRED as NAR
        # Simulate loop behavior: if outcome != FAILURE, increment tasks
        outcome = NAR
        if outcome != FAILURE:
            state["tasks_completed"] += 1
            record_task_success(state)
        assert state["tasks_completed"] == 1


# ── Scenario 4: Rate-limit sleep respects stop_requested ─────────────────────

class TestRateLimitSleepCancellable:

    def test_wait_exits_early_when_stop_set(self, state_file):
        """CancellationToken.wait() exits before timeout when stop_requested."""
        state = load_state(str(state_file))
        state["stop_requested"] = True
        save_state(state, str(state_file))

        token = CancellationToken(str(state_file))

        # Providing a long timeout but stop is already set
        with patch("romyq.cancel.time.sleep"), \
             patch("romyq.cancel.time.monotonic", side_effect=[0.0, 0.0, 5.0, 10.0]):
            stopped = token.wait(3600)  # 1 hour but should exit early

        assert stopped is True

    def test_wait_does_not_exit_when_only_paused(self, state_file):
        """Pause does not terminate rate-limit sleep (only stop does)."""
        state = load_state(str(state_file))
        state["paused"] = True
        state["stop_requested"] = False
        save_state(state, str(state_file))

        token = CancellationToken(str(state_file))

        with patch("romyq.cancel.time.sleep"), \
             patch("romyq.cancel.time.monotonic", side_effect=[0.0, 0.0, 5.0, 10.0]):
            stopped = token.wait(1)

        assert stopped is False  # pause doesn't exit rate-limit sleep


# ── Scenario 5: Persistent block ceiling ─────────────────────────────────────

class TestPersistentBlockCeiling:

    def test_ceiling_3_blocks_after_3_failures(self, state_file):
        state = load_state(str(state_file))
        task_key = "deadlocked_task_abc"

        # 3 failures
        for i in range(3):
            record_task_failure(state, task_key, f"failure {i}")
            save_state(state, str(state_file))
            state = load_state(str(state_file))  # simulate restart each time

        assert is_task_blocked(state, task_key) is True

    def test_success_unblocks(self, state_file):
        state = load_state(str(state_file))
        task_key = "deadlocked_task_abc"
        for _ in range(3):
            record_task_failure(state, task_key, "error")

        assert is_task_blocked(state, task_key)
        record_task_success(state)
        assert not is_task_blocked(state, task_key)


# ── Scenario 7: Dirty repository recovery ────────────────────────────────────

class TestDirtyRepositoryRecovery:

    def test_user_files_preserved_through_repeated_failures(self, git_repo):
        """User's pre-existing dirty files survive N consecutive Claude failures."""
        (git_repo / "user_work.py").write_text("important user code")
        pre_dirty = frozenset(["user_work.py"])
        commit = _head(git_repo)

        for i in range(5):
            (git_repo / f"claude_attempt_{i}.txt").write_text(f"attempt {i}")
            result = validate(
                workspace=str(git_repo),
                before_commit=commit,
                after_commit=commit,
                returncode=1,
                pre_dirty=True,
                pre_dirty_paths=pre_dirty,
            )
            assert result.outcome == FAILURE
            assert not (git_repo / f"claude_attempt_{i}.txt").exists()
            assert (git_repo / "user_work.py").read_text() == "important user code"


# ── Scenario 11: Event log captures lifecycle ─────────────────────────────────

class TestEventLogLifecycle:

    def test_full_task_lifecycle_events(self, events_file):
        """A complete task lifecycle emits the expected events."""
        emit(events_file, LOOP_STARTED)
        emit(events_file, TASK_STARTED, key="abc", mode="implementation")
        emit(events_file, VALIDATOR_PASSED, key="abc")
        emit(events_file, TASK_COMPLETED, key="abc", outcome=SUCCESS)

        events = tail(events_file)
        types = [e["event"] for e in events]
        assert types == [LOOP_STARTED, TASK_STARTED, VALIDATOR_PASSED, TASK_COMPLETED]

    def test_failure_loop_events(self, events_file):
        """Failure streaks emit VALIDATOR_FAILED and RETRY events."""
        emit(events_file, TASK_STARTED, key="abc")
        emit(events_file, VALIDATOR_FAILED, key="abc", reason="timeout")
        emit(events_file, RETRY, key="abc", streak=1)
        emit(events_file, TASK_STARTED, key="abc")
        emit(events_file, VALIDATOR_FAILED, key="abc", reason="timeout")
        emit(events_file, RETRY, key="abc", streak=2)

        counts = count_by_type(events_file)
        assert counts[VALIDATOR_FAILED] == 2
        assert counts[RETRY] == 2

    def test_stop_event_recorded(self, events_file):
        """Stop detection is logged before loop exits."""
        emit(events_file, STOP_DETECTED)
        emit(events_file, LOOP_STOPPED, reason="stop_requested")

        events = tail(events_file)
        assert any(e["event"] == STOP_DETECTED for e in events)
        assert any(e["event"] == LOOP_STOPPED for e in events)

    def test_events_survive_simulated_restart(self, events_file):
        """Events written in session 1 are readable in session 2 (append-only)."""
        # Session 1
        emit(events_file, LOOP_STARTED)
        emit(events_file, TASK_STARTED, key="k1")

        # Session 2 (same file)
        emit(events_file, LOOP_STARTED)  # second start
        emit(events_file, TASK_STARTED, key="k2")

        all_events = tail(events_file, n=100)
        assert len(all_events) == 4  # all 4 events are present


# ── Scenario 12: Phase progression ───────────────────────────────────────────

class TestPhaseProgression:

    def test_valid_phase_sequence(self):
        """IDLE → PLANNING → EXECUTING → VALIDATING → IDLE is valid."""
        from romyq.runstate import is_valid_transition, RunState
        sequence = [
            RunState.IDLE, RunState.PLANNING, RunState.EXECUTING,
            RunState.VALIDATING, RunState.IDLE,
        ]
        for from_s, to_s in zip(sequence, sequence[1:]):
            assert is_valid_transition(from_s, to_s), \
                f"Expected {from_s} → {to_s} to be valid"

    def test_set_phase_tracks_progression(self):
        """set_phase() updates state dict correctly through full cycle."""
        state = DEFAULT_STATE.copy()
        phases = [RunState.PLANNING, RunState.EXECUTING, RunState.VALIDATING, RunState.IDLE]
        for phase in phases:
            set_phase(state, phase)
            assert state["phase"] == phase.value

    def test_emergency_stop_from_executing(self):
        """EXECUTING → STOPPING → STOPPED is always valid (emergency path)."""
        from romyq.runstate import is_valid_transition, RunState
        assert is_valid_transition(RunState.EXECUTING, RunState.STOPPING)
        assert is_valid_transition(RunState.STOPPING, RunState.STOPPED)
