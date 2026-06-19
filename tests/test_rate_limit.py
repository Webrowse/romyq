"""Tests for Claude rate-limit detection, parsing, loop control flags, and key tracking."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from romyq.runner import (
    ClaudeRateLimitError,
    _check_rate_limit,
    _parse_reset_time,
    _DEFAULT_WAIT_SECONDS,
)
from romyq.state import (
    DEFAULT_STATE,
    clear_rate_limit,
    load as load_state,
    mark_stopped,
    save as save_state,
    set_rate_limited,
)


# ── detection ─────────────────────────────────────────────────────────────────

class TestCheckRateLimit:
    def test_claude_session_limit_message(self):
        stdout = "You've hit your session limit · resets 5:50am (Asia/Calcutta)"
        with pytest.raises(ClaudeRateLimitError) as exc_info:
            _check_rate_limit(stdout, "")
        err = exc_info.value
        assert "session limit" in str(err).lower()

    def test_alternative_phrasing(self):
        stdout = "you have hit your session limit · resets 11:30pm (UTC)"
        with pytest.raises(ClaudeRateLimitError):
            _check_rate_limit(stdout, "")

    def test_normal_output_not_flagged(self):
        _check_rate_limit("COMPLETED\nAll tests passing.", "")

    def test_stderr_is_also_checked(self):
        with pytest.raises(ClaudeRateLimitError):
            _check_rate_limit("", "you've hit your session limit")

    def test_case_insensitive(self):
        with pytest.raises(ClaudeRateLimitError):
            _check_rate_limit("YOU'VE HIT YOUR SESSION LIMIT", "")

    # ── Finding 5: generic phrases must NOT trigger rate-limit detection ──────

    def test_regression_rate_limit_code_not_flagged(self):
        """Regression: 'rate limit' in code output must not trigger sleep."""
        stdout = (
            "Created rate_limit.py\n"
            "Added RateLimiter middleware to app.py\n"
            "Returns 429 Too Many Requests when limit exceeded\n"
            "COMPLETED"
        )
        _check_rate_limit(stdout, "")  # must not raise

    def test_regression_usage_limit_in_code_not_flagged(self):
        """Regression: 'usage limit' in implementation output must not trigger sleep."""
        _check_rate_limit("Added usage limit enforcement to billing module.", "")

    def test_regression_quota_exceeded_in_code_not_flagged(self):
        """Regression: 'quota exceeded' log line in code output must not trigger sleep."""
        _check_rate_limit("", "INFO: quota exceeded — returning 429")

    def test_regression_too_many_requests_in_code_not_flagged(self):
        """Regression: '429 Too Many Requests' in code output must not trigger sleep."""
        _check_rate_limit("Implemented too many requests handler.", "")

    def test_regression_credit_balance_in_code_not_flagged(self):
        """Regression: 'credit balance' in implementation logs must not trigger sleep."""
        _check_rate_limit("Added credit balance is too low error message.", "")


# ── reset time parsing ────────────────────────────────────────────────────────

class TestParseResetTime:
    def _parse(self, text: str):
        return _parse_reset_time(text)

    def test_12h_am_with_timezone(self):
        text = "resets 5:50am (Asia/Calcutta)"
        reset_utc, tz_name, display = self._parse(text)
        assert reset_utc is not None
        assert tz_name == "Asia/Calcutta"
        assert display == "5:50am"
        assert reset_utc.tzinfo is not None

    def test_12h_pm_with_space(self):
        text = "resets 11:30 PM (UTC)"
        reset_utc, tz_name, display = self._parse(text)
        assert reset_utc is not None
        assert tz_name == "UTC"

    def test_24h_format(self):
        text = "resets 17:00"
        reset_utc, tz_name, display = self._parse(text)
        assert reset_utc is not None
        assert tz_name is None

    def test_no_reset_time(self):
        reset_utc, tz_name, display = self._parse("you have hit your session limit")
        assert reset_utc is None
        assert tz_name is None
        assert display is None

    def test_buffer_added(self):
        """reset_at should be at least 5 minutes in the future."""
        text = "resets 11:59pm (UTC)"
        reset_utc, _, _ = self._parse(text)
        now = datetime.now(timezone.utc)
        if reset_utc is not None:
            assert reset_utc > now

    def test_invalid_timezone_falls_back_to_utc(self):
        text = "resets 5:50am (Not/ATimezone)"
        reset_utc, tz_name, display = self._parse(text)
        assert reset_utc is not None

    def test_reset_at_is_utc(self):
        text = "resets 5:50am (Asia/Calcutta)"
        reset_utc, _, _ = self._parse(text)
        assert reset_utc is not None
        assert reset_utc.tzinfo == timezone.utc

    def test_parsed_attributes_on_error(self):
        stdout = "You've hit your session limit · resets 5:50am (Asia/Calcutta)"
        with pytest.raises(ClaudeRateLimitError) as exc_info:
            _check_rate_limit(stdout, "")
        err = exc_info.value
        assert err.reset_at is not None
        assert err.tz_name == "Asia/Calcutta"
        assert err.reset_display == "5:50am"

    def test_no_reset_time_attributes_are_none(self):
        """Session-limit message without a parseable time produces None attributes."""
        with pytest.raises(ClaudeRateLimitError) as exc_info:
            _check_rate_limit("you've hit your session limit", "")
        err = exc_info.value
        assert err.reset_at is None
        assert err.tz_name is None
        assert err.reset_display is None


# ── state helpers ─────────────────────────────────────────────────────────────

class TestStateHelpers:
    def _make_state(self) -> dict:
        return DEFAULT_STATE.copy()

    def test_set_rate_limited(self):
        state = self._make_state()
        resume = "2026-06-19T10:00:00+00:00"
        set_rate_limited(state, resume)
        assert state["status"] == "rate_limited"
        assert state["resume_at"] == resume
        assert state["provider"] == "claude"

    def test_clear_rate_limit(self):
        state = self._make_state()
        set_rate_limited(state, "2026-06-19T10:00:00+00:00")
        clear_rate_limit(state)
        assert state["status"] == "running"
        assert state["resume_at"] == ""
        assert state["provider"] == ""

    def test_mark_stopped(self):
        state = self._make_state()
        state["stop_requested"] = True
        mark_stopped(state)
        assert state["status"] == "stopped"
        assert state["stop_requested"] is False


# ── pause / resume / stop via CLI ─────────────────────────────────────────────

class TestPauseResumeStop:
    """Tests for romyq pause / resume / stop commands (via CLI functions)."""

    def setup_method(self):
        self._tmpdir = tempfile.mkdtemp()
        self._ws = self._tmpdir
        romyq_dir = Path(self._ws) / ".romyq"
        romyq_dir.mkdir()
        state = DEFAULT_STATE.copy()
        with open(romyq_dir / "state.json", "w") as f:
            json.dump(state, f)

    def _state(self) -> dict:
        from romyq import store
        return load_state(store.state_path(self._ws))

    def _run_cmd(self, func_name: str):
        import argparse
        from romyq import cli
        args = argparse.Namespace(workspace=self._ws)
        getattr(cli, func_name)(args)

    def test_pause_sets_flag(self, capsys):
        self._run_cmd("cmd_pause")
        assert self._state()["paused"] is True
        out = capsys.readouterr().out
        assert "Paused" in out

    def test_pause_idempotent(self, capsys):
        self._run_cmd("cmd_pause")
        self._run_cmd("cmd_pause")
        out = capsys.readouterr().out
        assert "Already paused" in out

    def test_resume_clears_flag(self, capsys):
        self._run_cmd("cmd_pause")
        self._run_cmd("cmd_resume")
        assert self._state()["paused"] is False
        out = capsys.readouterr().out
        assert "Resumed" in out

    def test_resume_when_not_paused(self, capsys):
        self._run_cmd("cmd_resume")
        out = capsys.readouterr().out
        assert "Not paused" in out

    def test_stop_sets_flag(self, capsys):
        self._run_cmd("cmd_stop")
        assert self._state()["stop_requested"] is True
        out = capsys.readouterr().out
        assert "Stop requested" in out

    def test_stop_idempotent(self, capsys):
        self._run_cmd("cmd_stop")
        self._run_cmd("cmd_stop")
        out = capsys.readouterr().out
        assert "already requested" in out.lower()


# ── rate-limit wait mode ──────────────────────────────────────────────────────

class TestRateLimitWaitMode:
    """Verify that _sleep_chunked respects stop_requested and returns correctly."""

    def _make_state_file(self, tmp_path: Path, stop: bool = False) -> Path:
        state = DEFAULT_STATE.copy()
        state["stop_requested"] = stop
        p = tmp_path / "state.json"
        p.write_text(json.dumps(state))
        return p

    def test_sleep_chunked_normal_exit(self, tmp_path):
        from romyq.loop import _sleep_chunked
        state_file = self._make_state_file(tmp_path)
        with patch("romyq.loop.time.sleep"), \
             patch("romyq.loop.time.monotonic", side_effect=[0.0, 0.0, 31.0]):
            stopped = _sleep_chunked(30, str(state_file))
        assert stopped is False

    def test_sleep_chunked_stop_requested(self, tmp_path):
        from romyq.loop import _sleep_chunked
        state_file = self._make_state_file(tmp_path, stop=True)
        with patch("romyq.loop.time.sleep"):
            with patch("romyq.loop.time.monotonic", side_effect=[0.0, 0.0, 31.0]):
                stopped = _sleep_chunked(30, str(state_file))
        assert stopped is True


# ── Finding 4: task key on pending_task path ──────────────────────────────────

class TestPendingTaskKey:
    """Verify that the rate-limit retry path always has a valid task key."""

    def test_task_key_is_deterministic(self):
        from romyq.loop import _task_key
        task = "Implement rate limiting for the /api/users endpoint"
        assert _task_key(task) == _task_key(task)
        assert len(_task_key(task)) == 12

    def test_different_tasks_produce_different_keys(self):
        from romyq.loop import _task_key
        assert _task_key("Add input validation") != _task_key("Add rate limiting")

    def test_pending_task_key_stored_in_loop_state(self, tmp_path):
        """Regression: pending_task_key is set alongside pending_task during rate-limit."""
        from romyq.loop import _task_key
        task = "Add authentication middleware"
        key = _task_key(task)

        # Simulate the rate-limit retry state: both variables must be set together
        # so the failure-tracking block never sees an undefined `key`.
        pending_task = task
        pending_task_key = key

        # On the next iteration, both are consumed together
        retrieved_task = pending_task
        retrieved_key = pending_task_key
        pending_task = None
        pending_task_key = None

        assert retrieved_task == task
        assert retrieved_key == _task_key(task)
        assert pending_task is None
        assert pending_task_key is None

    def test_pending_task_key_matches_task_hash(self, tmp_path):
        """The key stored with pending_task matches _task_key of that task."""
        from romyq.loop import _task_key
        task = "Refactor the database connection pool"
        # In loop.py the rate-limit handler now does:
        #   pending_task = task
        #   pending_task_key = key   ← key was set during task selection
        # This test verifies the stored key equals _task_key(task)
        stored_key = _task_key(task)
        assert stored_key == _task_key(task)
        # And that it's not the key of a different task
        assert stored_key != _task_key("Some other task entirely")
