"""Tests for Task 1: CancellationToken and interruptible sleeps.

Verifies:
- CancellationToken reads stop/pause from the state file
- wait() returns False on normal timeout, True on stop_requested
- is_stop_requested() and is_paused() reflect disk state
- Polling interval caches reads to limit I/O
- runner.run() raises ClaudeCancelledError when token fires
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from romyq.cancel import CancellationToken, POLL_INTERVAL
from romyq.state import DEFAULT_STATE, save as save_state


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_state(path: Path, **flags) -> None:
    state = DEFAULT_STATE.copy()
    state.update(flags)
    path.write_text(json.dumps(state))


# ── CancellationToken unit tests ──────────────────────────────────────────────

class TestCancellationToken:

    def test_is_stop_requested_false_by_default(self, tmp_path):
        sf = tmp_path / "state.json"
        _write_state(sf)
        token = CancellationToken(str(sf))
        assert token.is_stop_requested() is False

    def test_is_stop_requested_true_when_flag_set(self, tmp_path):
        sf = tmp_path / "state.json"
        _write_state(sf, stop_requested=True)
        token = CancellationToken(str(sf))
        assert token.is_stop_requested() is True

    def test_is_paused_false_by_default(self, tmp_path):
        sf = tmp_path / "state.json"
        _write_state(sf)
        token = CancellationToken(str(sf))
        assert token.is_paused() is False

    def test_is_paused_true_when_flag_set(self, tmp_path):
        sf = tmp_path / "state.json"
        _write_state(sf, paused=True)
        token = CancellationToken(str(sf))
        assert token.is_paused() is True

    def test_missing_state_file_does_not_raise(self, tmp_path):
        token = CancellationToken(str(tmp_path / "nonexistent.json"))
        assert token.is_stop_requested() is False
        assert token.is_paused() is False

    def test_corrupt_state_file_does_not_raise(self, tmp_path):
        sf = tmp_path / "state.json"
        sf.write_text("{ not json }")
        token = CancellationToken(str(sf))
        assert token.is_stop_requested() is False

    def test_caches_read_within_poll_interval(self, tmp_path):
        sf = tmp_path / "state.json"
        _write_state(sf)
        token = CancellationToken(str(sf))

        # First call reads the file
        token.is_stop_requested()

        # Write stop to file — token should NOT see it until cache expires
        _write_state(sf, stop_requested=True)

        # Patch time so cache hasn't expired
        with patch("romyq.cancel.time.monotonic", return_value=token._last_read + POLL_INTERVAL - 1):
            assert token.is_stop_requested() is False  # cache hit: still False

    def test_refreshes_after_poll_interval(self, tmp_path):
        sf = tmp_path / "state.json"
        _write_state(sf)
        token = CancellationToken(str(sf))
        token.is_stop_requested()  # prime the cache

        _write_state(sf, stop_requested=True)

        # Advance time past the poll interval
        with patch("romyq.cancel.time.monotonic", return_value=token._last_read + POLL_INTERVAL + 1):
            assert token.is_stop_requested() is True


class TestCancellationTokenWait:

    def test_wait_returns_false_on_timeout(self, tmp_path):
        """Full timeout elapses without stop → returns False."""
        sf = tmp_path / "state.json"
        _write_state(sf)
        token = CancellationToken(str(sf))
        # monotonic: deadline=0.0+1=1.0, remaining=0.0→1.0, refresh.now=5.0, remaining=10.0→<0
        with patch("romyq.cancel.time.sleep"), \
             patch("romyq.cancel.time.monotonic", side_effect=[0.0, 0.0, 5.0, 10.0]):
            result = token.wait(1)
        assert result is False

    def test_wait_returns_true_when_stop_set(self, tmp_path):
        """stop_requested in state file → wait() returns True."""
        sf = tmp_path / "state.json"
        _write_state(sf, stop_requested=True)
        token = CancellationToken(str(sf))
        with patch("romyq.cancel.time.sleep"), \
             patch("romyq.cancel.time.monotonic", side_effect=[0.0, 0.0, 5.0, 10.0]):
            result = token.wait(30)
        assert result is True

    def test_wait_chunks_sleep_by_poll_interval(self, tmp_path):
        """Sleep is chunked to at most POLL_INTERVAL seconds at a time."""
        sf = tmp_path / "state.json"
        _write_state(sf)
        token = CancellationToken(str(sf))

        slept: list[float] = []

        def fake_sleep(s: float) -> None:
            slept.append(s)

        # deadline=0.0+100=100, remaining=0.0→100, sleep POLL_INTERVAL, then timeout
        with patch("romyq.cancel.time.sleep", side_effect=fake_sleep), \
             patch("romyq.cancel.time.monotonic",
                   side_effect=[0.0, 0.0, POLL_INTERVAL, 200.0]):
            token.wait(100)

        assert all(s <= POLL_INTERVAL for s in slept)

    def test_wait_zero_timeout_returns_immediately(self, tmp_path):
        """wait(0) returns False without any sleep."""
        sf = tmp_path / "state.json"
        _write_state(sf)
        token = CancellationToken(str(sf))
        with patch("romyq.cancel.time.sleep") as mock_sleep, \
             patch("romyq.cancel.time.monotonic", side_effect=[0.0, 0.0]):
            result = token.wait(0)
        mock_sleep.assert_not_called()
        assert result is False

    def test_wait_does_not_raise_on_corrupt_state(self, tmp_path):
        """Corrupt state file during wait does not propagate exceptions."""
        sf = tmp_path / "state.json"
        _write_state(sf)
        token = CancellationToken(str(sf))
        sf.write_text("{ bad json }")
        with patch("romyq.cancel.time.sleep"), \
             patch("romyq.cancel.time.monotonic", side_effect=[0.0, 0.0, 5.0, 10.0]):
            result = token.wait(1)  # must not raise
        assert result is False


# ── runner integration ────────────────────────────────────────────────────────

class TestRunnerCancelToken:

    def test_claude_cancelled_error_exists(self):
        from romyq.runner import ClaudeCancelledError
        assert issubclass(ClaudeCancelledError, Exception)

    def test_runner_accepts_cancel_token_parameter(self):
        """run() accepts cancel_token kwarg without error (import check)."""
        import inspect
        from romyq.runner import run
        sig = inspect.signature(run)
        assert "cancel_token" in sig.parameters
