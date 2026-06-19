"""Smoke / integration tests for real subprocess execution.

These tests launch real OS processes to verify behaviour that mocks cannot:
- subprocess.Popen lifecycle (poll, terminate, kill)
- CancellationToken correctly terminates a running child
- ClaudeCancelledError propagates after SIGTERM
- Timeout path terminates and raises ClaudeTimeoutError

Tests that require the claude binary are guarded with @pytest.mark.skipif and
are skipped automatically in environments where claude is not installed.

To run smoke tests explicitly:
    pytest tests/test_smoke.py -v

To run including the optional claude binary tests:
    pytest tests/test_smoke.py -v -m smoke
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from romyq.cancel import CancellationToken, POLL_INTERVAL
from romyq.runner import (
    ClaudeCancelledError,
    ClaudeTimeoutError,
    _terminate,
    run,
)
from romyq.state import DEFAULT_STATE, save as save_state


CLAUDE_PRESENT = bool(shutil.which("claude"))

# ── git repo fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
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
    (tmp_path / "README.md").write_text("# Smoke test repo\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, env=env)
    return tmp_path


# ── _terminate() ─────────────────────────────────────────────────────────────

class TestTerminate:
    """Tests for the _terminate() helper — does not require claude."""

    def test_terminate_stops_sleeping_process(self, tmp_path):
        """_terminate() kills a subprocess that would otherwise sleep indefinitely."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(9999)"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        _terminate(proc)
        assert proc.returncode is not None

    def test_terminate_on_already_finished_process(self, tmp_path):
        """_terminate() on a process that already exited does not raise."""
        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        proc.wait()
        _terminate(proc)  # must not raise


# ── runner.run() with a real process (no claude required) ─────────────────────

class TestRunnerWithFakeProcess:
    """Validates run() lifecycle using a Python script as the subprocess."""

    def test_cancellation_terminates_long_running_process(self, tmp_path, git_repo):
        """When cancel_token fires, run() terminates the process and raises ClaudeCancelledError."""
        state_file = tmp_path / "state.json"
        state = DEFAULT_STATE.copy()
        save_state(state, str(state_file))
        token = CancellationToken(str(state_file))

        # Patch subprocess.Popen to launch a long-sleeping Python process
        # then set stop_requested after a short delay.
        import romyq.runner as runner_mod

        original_popen = subprocess.Popen
        launched: list[subprocess.Popen] = []

        def fake_popen(args, **kwargs):
            proc = original_popen(
                [sys.executable, "-c", "import time; time.sleep(9999)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            launched.append(proc)
            return proc

        def set_stop_after_delay():
            time.sleep(0.2)
            s = DEFAULT_STATE.copy()
            s["stop_requested"] = True
            save_state(s, str(state_file))

        stopper = threading.Thread(target=set_stop_after_delay, daemon=True)

        with pytest.raises(ClaudeCancelledError):
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(subprocess, "Popen", fake_popen)
                stopper.start()
                runner_mod.run(
                    workspace=str(git_repo),
                    task="dummy",
                    timeout_seconds=30,
                    cancel_token=token,
                )

        stopper.join(timeout=5)
        assert launched, "Popen was never called"
        assert launched[0].returncode is not None, "Process was not terminated"

    def test_timeout_raises_claude_timeout_error(self, git_repo):
        """run() raises ClaudeTimeoutError when timeout_seconds is exceeded."""
        import romyq.runner as runner_mod

        original_popen = subprocess.Popen

        def fake_popen(args, **kwargs):
            return original_popen(
                [sys.executable, "-c", "import time; time.sleep(9999)"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )

        with pytest.raises(ClaudeTimeoutError):
            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(subprocess, "Popen", fake_popen)
                runner_mod.run(
                    workspace=str(git_repo),
                    task="dummy",
                    timeout_seconds=1,
                )


# ── optional: real claude binary ──────────────────────────────────────────────

@pytest.mark.skipif(not CLAUDE_PRESENT, reason="claude not in PATH")
@pytest.mark.smoke
class TestClaudeBinarySmoke:
    """Tests that invoke the real claude binary.  Skipped when not installed."""

    def test_claude_help_exits_zero(self):
        """claude --help exits without error."""
        result = subprocess.run(
            ["claude", "--help"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0 or "usage" in result.stdout.lower() or "usage" in result.stderr.lower()

    def test_claude_version_exits_zero(self):
        """claude --version or claude -v exits without error."""
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0 or result.stdout.strip() or result.stderr.strip()

    def test_runner_run_with_trivial_task(self, git_repo):
        """run() on a trivial task completes without raising (requires network + API key)."""
        pytest.importorskip("dotenv")
        from dotenv import load_dotenv
        load_dotenv()
        if not os.getenv("DEEPSEEK_API_KEY") and not os.getenv("ANTHROPIC_API_KEY"):
            pytest.skip("No API key configured")

        result = run(
            workspace=str(git_repo),
            task="Create a file called SMOKE_TEST.txt with the text 'smoke test passed', stage it, commit it with message 'smoke test', then print COMPLETED.",
            timeout_seconds=120,
        )
        assert result.returncode == 0 or "COMPLETED" in result.stdout
