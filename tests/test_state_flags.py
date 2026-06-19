"""Tests for Finding 1: state write-after-read race condition.

The loop holds an in-memory state dict for up to 30+ minutes (the Claude
execution window).  Any CLI write to pause/stop flags during that window
would previously be silently overwritten by the loop's end-of-iteration
save_state() call.

refresh_control_flags() fixes this by re-reading those flags from disk
immediately before every save.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq.state import (
    DEFAULT_STATE,
    load as load_state,
    refresh_control_flags,
    save as save_state,
)


@pytest.fixture
def state_file(tmp_path: Path) -> Path:
    p = tmp_path / "state.json"
    state = DEFAULT_STATE.copy()
    save_state(state, str(p))
    return p


# ── refresh_control_flags unit tests ─────────────────────────────────────────

class TestRefreshControlFlags:

    def test_picks_up_pause_from_disk(self, state_file):
        """paused=True written to disk is merged into in-memory dict."""
        # Simulate CLI write: disk has paused=True
        disk = load_state(str(state_file))
        disk["paused"] = True
        save_state(disk, str(state_file))

        # Loop has stale in-memory state with paused=False
        mem = DEFAULT_STATE.copy()
        assert mem["paused"] is False

        refresh_control_flags(mem, str(state_file))
        assert mem["paused"] is True

    def test_picks_up_stop_requested_from_disk(self, state_file):
        """stop_requested=True written to disk is merged into in-memory dict."""
        disk = load_state(str(state_file))
        disk["stop_requested"] = True
        save_state(disk, str(state_file))

        mem = DEFAULT_STATE.copy()
        assert mem["stop_requested"] is False

        refresh_control_flags(mem, str(state_file))
        assert mem["stop_requested"] is True

    def test_does_not_overwrite_operational_fields(self, state_file):
        """refresh only touches control flags, not tasks_completed etc."""
        disk = load_state(str(state_file))
        disk["paused"] = True
        disk["tasks_completed"] = 99  # stale disk value
        save_state(disk, str(state_file))

        mem = DEFAULT_STATE.copy()
        mem["tasks_completed"] = 5  # current in-memory value (authoritative)

        refresh_control_flags(mem, str(state_file))

        assert mem["paused"] is True          # flag updated from disk
        assert mem["tasks_completed"] == 5    # operational field preserved

    def test_handles_missing_file_gracefully(self, tmp_path):
        """refresh does not raise if the state file does not exist."""
        mem = DEFAULT_STATE.copy()
        refresh_control_flags(mem, str(tmp_path / "nonexistent.json"))
        # No exception — mem is unchanged
        assert mem["paused"] is False
        assert mem["stop_requested"] is False

    def test_handles_corrupt_file_gracefully(self, tmp_path):
        """refresh does not raise if the state file contains invalid JSON."""
        bad = tmp_path / "state.json"
        bad.write_text("{ not valid json }")
        mem = DEFAULT_STATE.copy()
        refresh_control_flags(mem, str(bad))
        assert mem["paused"] is False

    def test_resume_flag_propagates_correctly(self, state_file):
        """paused going False→True→False: each transition is picked up."""
        mem = DEFAULT_STATE.copy()

        # Pause
        disk = load_state(str(state_file))
        disk["paused"] = True
        save_state(disk, str(state_file))
        refresh_control_flags(mem, str(state_file))
        assert mem["paused"] is True

        # Resume
        disk = load_state(str(state_file))
        disk["paused"] = False
        save_state(disk, str(state_file))
        refresh_control_flags(mem, str(state_file))
        assert mem["paused"] is False


# ── regression: race-condition scenarios ─────────────────────────────────────

class TestRaceConditionRegression:

    def test_regression_cli_stop_survives_loop_save(self, state_file):
        """Regression: stop_requested written by CLI is not overwritten by loop save.

        Before the fix, this sequence silently discarded the stop:
          1. Loop loads state (stop_requested=False) into mem
          2. CLI writes stop_requested=True to disk
          3. Loop saves mem → disk: stop_requested=False  ← BUG
        After the fix, refresh_control_flags() at step 3 merges disk first.
        """
        # Step 1: loop loads state
        mem = load_state(str(state_file))
        assert mem["stop_requested"] is False

        # Step 2: CLI writes stop during Claude execution
        cli_state = load_state(str(state_file))
        cli_state["stop_requested"] = True
        save_state(cli_state, str(state_file))

        # Verify CLI write landed on disk
        assert load_state(str(state_file))["stop_requested"] is True

        # Step 3: loop refreshes then saves (the fix)
        mem["tasks_completed"] += 1  # simulate task completing
        refresh_control_flags(mem, str(state_file))
        save_state(mem, str(state_file))

        # stop_requested must survive
        final = load_state(str(state_file))
        assert final["stop_requested"] is True

    def test_regression_cli_pause_survives_loop_save(self, state_file):
        """Regression: paused=True written by CLI is not overwritten by loop save."""
        mem = load_state(str(state_file))

        # CLI pauses during task
        cli_state = load_state(str(state_file))
        cli_state["paused"] = True
        save_state(cli_state, str(state_file))

        # Loop finishes task and saves with refresh
        refresh_control_flags(mem, str(state_file))
        save_state(mem, str(state_file))

        final = load_state(str(state_file))
        assert final["paused"] is True

    def test_regression_without_refresh_flag_is_lost(self, state_file):
        """Demonstrates the pre-fix behavior: save without refresh loses the flag."""
        mem = load_state(str(state_file))

        # CLI writes stop
        cli_state = load_state(str(state_file))
        cli_state["stop_requested"] = True
        save_state(cli_state, str(state_file))

        # Loop saves WITHOUT refresh (old behavior)
        save_state(mem, str(state_file))

        # Flag is lost — this is the bug being fixed
        final = load_state(str(state_file))
        assert final["stop_requested"] is False  # demonstrates the race

    def test_multiple_flags_both_refreshed(self, state_file):
        """Both paused and stop_requested are refreshed in a single call."""
        mem = load_state(str(state_file))

        disk = load_state(str(state_file))
        disk["paused"] = True
        disk["stop_requested"] = True
        save_state(disk, str(state_file))

        refresh_control_flags(mem, str(state_file))

        assert mem["paused"] is True
        assert mem["stop_requested"] is True
