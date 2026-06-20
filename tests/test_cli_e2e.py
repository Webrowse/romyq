"""End-to-end CLI integration tests.

These tests execute the *real* CLI entrypoint as a subprocess so that
import-time errors, missing dependencies, and broken argument parsing are
all caught exactly as a user would experience them.

No mocks of cli.py, wizard.py, or loop.py.

Running: pytest tests/test_cli_e2e.py -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _romyq(*args: str, cwd: Path | None = None, input: str | None = None,
           env: dict | None = None, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run `romyq <args>` as a real subprocess."""
    base_env = {**os.environ}
    if env:
        base_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "romyq.cli"] + list(args),
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        input=input,
        timeout=timeout,
        env=base_env,
    )


@pytest.fixture()
def workspace(tmp_path, monkeypatch):
    """Isolated temp workspace with git identity configured."""
    env = {
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@test.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@test.com",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def initialized_workspace(workspace):
    """Workspace that has already been through non-interactive init."""
    r = _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
    assert r.returncode == 0, f"init failed: {r.stderr}"
    return workspace


@pytest.fixture()
def running_workspace(initialized_workspace):
    """Workspace with state.json written as if a loop run has happened."""
    from romyq import store
    from romyq.state import DEFAULT_STATE, save as save_state
    s = dict(DEFAULT_STATE)
    s["status"] = "running"
    s["tasks_completed"] = 3
    s["heartbeat"] = "2025-01-01T10:00:00+00:00"
    s["last_commit"] = "abc1234"
    save_state(s, store.state_path(str(initialized_workspace)))
    return initialized_workspace


# ── romyq version ─────────────────────────────────────────────────────────────

class TestVersion:
    def test_exits_zero(self, tmp_path):
        r = _romyq("version", cwd=tmp_path)
        assert r.returncode == 0

    def test_prints_version_number(self, tmp_path):
        r = _romyq("version", cwd=tmp_path)
        assert "romyq" in r.stdout
        assert "0.9." in r.stdout or "0.8." in r.stdout or "." in r.stdout

    def test_no_import_errors(self, tmp_path):
        r = _romyq("version", cwd=tmp_path)
        assert "Error" not in r.stderr
        assert "Traceback" not in r.stderr


# ── romyq init --no-wizard ────────────────────────────────────────────────────

class TestInitNoWizard:
    def test_exits_zero(self, workspace):
        r = _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert r.returncode == 0, r.stderr

    def test_creates_romyq_dir(self, workspace):
        _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert (workspace / ".romyq").is_dir()

    def test_creates_mission_md(self, workspace):
        _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert (workspace / "mission.md").exists()

    def test_no_traceback(self, workspace):
        r = _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert "Traceback" not in r.stderr
        assert "NameError" not in r.stderr

    def test_idempotent(self, workspace):
        r1 = _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        r2 = _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert r1.returncode == 0
        assert r2.returncode == 0

    def test_does_not_start_loop(self, workspace):
        """init --no-wizard must not generate plans or start execution."""
        r = _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert "Romyq started" not in r.stdout
        assert "Task" not in r.stdout
        assert "plan.json" not in (workspace / ".romyq").name if (workspace / ".romyq").exists() else True
        # No plan.json should be created by init alone
        assert not (workspace / ".romyq" / "plan.json").exists()

    def test_does_not_generate_knowledge(self, workspace):
        _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert not (workspace / ".romyq" / "knowledge.json").exists()

    def test_does_not_generate_context(self, workspace):
        _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert not (workspace / ".romyq" / "context.md").exists()


# ── romyq init (text wizard, non-interactive) ─────────────────────────────────

try:
    import textual as _textual  # noqa: F401
    _TEXTUAL_INSTALLED = True
except ImportError:
    _TEXTUAL_INSTALLED = False

_skip_if_textual = pytest.mark.skipif(
    _TEXTUAL_INSTALLED,
    reason="Textual TUI intercepts stdin — text-mode tests require textual not installed",
)


class TestInitWizardTextMode:
    """Run the text-mode wizard with stdin piped so it doesn't block.

    Skipped when Textual is installed because Textual takes over stdin/stdout
    and cannot be driven non-interactively via subprocess piped input.
    """

    @_skip_if_textual
    def test_exits_cleanly_with_n_to_all_prompts(self, workspace):
        # Provider=N, demo mission, Start Now=N
        r = _romyq("init", str(workspace), cwd=workspace,
                   input="N\n1\nN\n", timeout=15)
        assert "NameError" not in r.stderr
        assert "Traceback" not in r.stderr

    @_skip_if_textual
    def test_no_nameerror_in_wizard_output(self, workspace):
        r = _romyq("init", str(workspace), cwd=workspace,
                   input="N\n1\nN\n", timeout=15)
        assert "NameError" not in r.stderr
        assert "NameError" not in r.stdout


# ── romyq doctor ──────────────────────────────────────────────────────────────

class TestDoctor:
    def test_exits_zero_after_init(self, initialized_workspace):
        r = _romyq("doctor", str(initialized_workspace), cwd=initialized_workspace)
        assert r.returncode == 0, r.stdout + r.stderr

    def test_no_traceback(self, initialized_workspace):
        r = _romyq("doctor", str(initialized_workspace), cwd=initialized_workspace)
        assert "Traceback" not in r.stderr

    def test_shows_checks(self, initialized_workspace):
        r = _romyq("doctor", str(initialized_workspace), cwd=initialized_workspace)
        assert "✓" in r.stdout or "✗" in r.stdout


# ── romyq health ──────────────────────────────────────────────────────────────

class TestHealth:
    def test_no_state_exits_nonzero_or_message(self, initialized_workspace):
        r = _romyq("health", str(initialized_workspace), cwd=initialized_workspace)
        # Either exits 0 with "not yet run" message or exits non-zero
        assert r.returncode == 0 or "not yet" in r.stdout.lower() or "has romyq" in r.stdout.lower()

    def test_no_traceback(self, initialized_workspace):
        r = _romyq("health", str(initialized_workspace), cwd=initialized_workspace)
        assert "Traceback" not in r.stderr

    def test_shows_status_with_state(self, running_workspace):
        r = _romyq("health", str(running_workspace), cwd=running_workspace)
        assert r.returncode == 0
        assert "status" in r.stdout.lower() or "running" in r.stdout.lower()

    def test_no_nameerror_with_state(self, running_workspace):
        r = _romyq("health", str(running_workspace), cwd=running_workspace)
        assert "NameError" not in r.stderr


# ── romyq status ──────────────────────────────────────────────────────────────

class TestStatus:
    def test_json_output_valid(self, running_workspace):
        r = _romyq("status", "--json", str(running_workspace), cwd=running_workspace)
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert "status" in data
        assert "tasks_completed" in data

    def test_no_traceback(self, running_workspace):
        r = _romyq("status", str(running_workspace), cwd=running_workspace)
        assert "Traceback" not in r.stderr

    def test_shows_current_status(self, running_workspace):
        r = _romyq("status", str(running_workspace), cwd=running_workspace)
        assert "running" in r.stdout


# ── romyq pause ───────────────────────────────────────────────────────────────

class TestPause:
    def test_exits_zero(self, running_workspace):
        r = _romyq("pause", str(running_workspace), cwd=running_workspace)
        assert r.returncode == 0

    def test_sets_paused_flag(self, running_workspace):
        _romyq("pause", str(running_workspace), cwd=running_workspace)
        from romyq import store
        from romyq.state import load as load_state
        state = load_state(store.state_path(str(running_workspace)))
        assert state["paused"] is True

    def test_prints_confirmation(self, running_workspace):
        r = _romyq("pause", str(running_workspace), cwd=running_workspace)
        out = r.stdout.upper()
        assert "PAUSE" in out or "paused" in out.lower()

    def test_no_traceback(self, running_workspace):
        r = _romyq("pause", str(running_workspace), cwd=running_workspace)
        assert "Traceback" not in r.stderr

    def test_idempotent(self, running_workspace):
        _romyq("pause", str(running_workspace), cwd=running_workspace)
        r = _romyq("pause", str(running_workspace), cwd=running_workspace)
        assert r.returncode == 0
        assert "already" in r.stdout.lower()


# ── romyq resume ──────────────────────────────────────────────────────────────

class TestResume:
    def test_exits_zero_when_paused(self, running_workspace):
        _romyq("pause", str(running_workspace), cwd=running_workspace)
        r = _romyq("resume", str(running_workspace), cwd=running_workspace)
        assert r.returncode == 0

    def test_clears_paused_flag(self, running_workspace):
        _romyq("pause", str(running_workspace), cwd=running_workspace)
        _romyq("resume", str(running_workspace), cwd=running_workspace)
        from romyq import store
        from romyq.state import load as load_state
        state = load_state(store.state_path(str(running_workspace)))
        assert not state.get("paused", False)

    def test_prints_confirmation(self, running_workspace):
        _romyq("pause", str(running_workspace), cwd=running_workspace)
        r = _romyq("resume", str(running_workspace), cwd=running_workspace)
        out = r.stdout.upper()
        assert "RESUME" in out or "resume" in out.lower()

    def test_not_paused_message(self, running_workspace):
        r = _romyq("resume", str(running_workspace), cwd=running_workspace)
        assert "not paused" in r.stdout.lower()

    def test_no_traceback(self, running_workspace):
        r = _romyq("resume", str(running_workspace), cwd=running_workspace)
        assert "Traceback" not in r.stderr


# ── romyq stop ────────────────────────────────────────────────────────────────

class TestStop:
    def test_exits_zero(self, running_workspace):
        r = _romyq("stop", str(running_workspace), cwd=running_workspace)
        assert r.returncode == 0

    def test_sets_stop_flag(self, running_workspace):
        _romyq("stop", str(running_workspace), cwd=running_workspace)
        from romyq import store
        from romyq.state import load as load_state
        state = load_state(store.state_path(str(running_workspace)))
        assert state["stop_requested"] is True

    def test_prints_confirmation(self, running_workspace):
        r = _romyq("stop", str(running_workspace), cwd=running_workspace)
        out = r.stdout.upper()
        assert "STOP" in out

    def test_idempotent(self, running_workspace):
        _romyq("stop", str(running_workspace), cwd=running_workspace)
        r = _romyq("stop", str(running_workspace), cwd=running_workspace)
        assert r.returncode == 0
        assert "already" in r.stdout.lower()

    def test_no_traceback(self, running_workspace):
        r = _romyq("stop", str(running_workspace), cwd=running_workspace)
        assert "Traceback" not in r.stderr


# ── romyq run (loop.run import test) ─────────────────────────────────────────

class TestLoopRunImport:
    """These tests verify loop.run() can be imported and called without
    hitting the sys NameError that caused the 0.9.0 production failure.
    They do not require a real API key or Claude installation.
    """

    def test_loop_module_importable(self):
        """The loop module must import without errors."""
        import importlib
        import romyq.loop as loop_mod
        # Re-import to force module-level code to run again
        importlib.reload(loop_mod)

    def test_sys_is_imported_in_loop(self):
        """Regression: sys must be at module level in loop.py."""
        import romyq.loop as loop_mod
        import inspect
        src = inspect.getsource(loop_mod)
        lines = src.splitlines()
        # Find top-level import sys (not inside a function)
        import_sys_found = False
        in_function = False
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("class "):
                in_function = True
            if not in_function and stripped == "import sys":
                import_sys_found = True
                break
        assert import_sys_found, (
            "REGRESSION: 'import sys' not found at module level in loop.py. "
            "This caused the 0.9.0 production NameError."
        )

    def test_loop_run_reaches_sys_isatty_without_nameerror(self, initialized_workspace, monkeypatch):
        """loop.run() must not raise NameError before reaching the API call."""
        import romyq.workspace as ws_mod
        import romyq.context as ctx_mod
        import romyq.knowledge as know_mod
        import romyq.decomposition as dec_mod

        # Stub out network calls and git operations
        monkeypatch.setattr(ws_mod, "bootstrap", lambda p: None)
        monkeypatch.setattr(ctx_mod, "write", lambda *a, **kw: None)
        monkeypatch.setattr(ctx_mod, "load", lambda *a, **kw: "")
        monkeypatch.setattr(know_mod, "is_stale", lambda *a, **kw: False)
        monkeypatch.setattr(dec_mod, "decompose", lambda *a, **kw: {
            "version": 1, "generated_at": "x", "tasks": [],
        })

        # Make the loop stop immediately after startup
        import romyq.state as state_mod
        original_load = state_mod.load
        call_count = [0]
        def stopping_load(path):
            s = original_load(path)
            call_count[0] += 1
            if call_count[0] > 1:
                s["stop_requested"] = True
            return s
        monkeypatch.setattr(state_mod, "load", stopping_load)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "fake-key-for-test")

        from romyq.loop import run
        # Should reach stop cleanly, not NameError
        try:
            run(str(initialized_workspace))
        except SystemExit:
            pass
        except Exception as e:
            # AuthenticationError / network errors are fine — means we got past line 278
            err = str(e)
            assert "NameError" not in err, f"NameError regression: {e}"
            assert "name 'sys'" not in err, f"NameError regression (sys): {e}"


# ── romyq run (subprocess, stops immediately via stop flag) ───────────────────

class TestRunSubprocess:
    """Smoke-tests for `romyq run` as a subprocess.

    We cannot run the full loop (requires Claude + DeepSeek), but we can
    verify the entrypoint reaches execution without crashing on import or
    argument parsing errors.
    """

    def test_run_exits_on_missing_mission(self, initialized_workspace):
        """romyq run without mission.md must exit non-zero, not crash."""
        (initialized_workspace / "mission.md").unlink()
        r = _romyq("run", str(initialized_workspace), cwd=initialized_workspace,
                   env={"DEEPSEEK_API_KEY": ""})
        assert r.returncode != 0
        assert "Traceback" not in r.stderr or "mission" in r.stdout.lower()

    def test_run_exits_on_missing_api_key(self, initialized_workspace):
        """romyq run without DEEPSEEK_API_KEY must exit with a clear message."""
        r = _romyq("run", str(initialized_workspace), cwd=initialized_workspace,
                   env={"DEEPSEEK_API_KEY": ""})
        assert r.returncode != 0
        assert "DEEPSEEK_API_KEY" in r.stdout or "DEEPSEEK_API_KEY" in r.stderr

    def test_run_no_nameerror_on_startup(self, initialized_workspace):
        """NameError regression: run must not crash on 'sys' at startup."""
        r = _romyq("run", str(initialized_workspace), cwd=initialized_workspace,
                   env={"DEEPSEEK_API_KEY": ""})
        assert "NameError" not in r.stderr
        assert "name 'sys'" not in r.stderr


# ── init side-effect isolation ─────────────────────────────────────────────────

class TestInitSideEffects:
    """Verify init does not produce side-effects that belong to 'run'."""

    def test_init_does_not_write_state_json(self, workspace):
        _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        # state.json should NOT exist after init — only written by loop.run()
        assert not (workspace / ".romyq" / "state.json").exists()

    def test_init_does_not_write_history_json(self, workspace):
        _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert not (workspace / ".romyq" / "history.json").exists()

    def test_init_does_not_write_plan_json(self, workspace):
        _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert not (workspace / ".romyq" / "plan.json").exists()

    def test_init_does_not_write_events_log(self, workspace):
        _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        assert not (workspace / ".romyq" / "events.log").exists()

    def test_init_files_are_exactly(self, workspace):
        """After init, only .romyq/ and mission.md should exist in workspace root."""
        _romyq("init", "--no-wizard", str(workspace), cwd=workspace)
        created = {p.name for p in workspace.iterdir()}
        # Expected: .romyq/, mission.md, .git/ (from bootstrap), .gitignore
        unexpected = created - {".romyq", "mission.md", ".git", ".gitignore"}
        assert not unexpected, f"Unexpected files created by init: {unexpected}"
