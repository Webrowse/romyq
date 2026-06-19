"""Tests for romyq status --json and romyq explain.

Verifies:
- status --json outputs valid JSON containing all expected state keys
- status --json round-trips: parsed JSON matches the state written to disk
- status --json does not output human-formatted text
- romyq explain shows phase, task, attempts, failures, and evidence sections
- romyq explain handles zero-failures state gracefully
- romyq explain handles missing evidence gracefully
- romyq explain shows BLOCKED label when attempts >= ceiling
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from romyq.state import DEFAULT_STATE, record_task_failure, save as save_state
from romyq import store


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    store.ensure_dir(str(ws))
    s = DEFAULT_STATE.copy()
    save_state(s, store.state_path(str(ws)))
    return ws


@pytest.fixture
def workspace_with_failures(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    store.ensure_dir(str(ws))
    s = DEFAULT_STATE.copy()
    s["current_task"] = "Implement the authentication module."
    s["phase"] = "idle"
    s["tasks_completed"] = 3
    s["last_commit"] = "abc1234"
    record_task_failure(s, "key_abc123", "No new commit created")
    record_task_failure(s, "key_abc123", "Claude exited with non-zero status")
    s["last_validation_evidence"] = [
        "exit_code=1",
        "outcome=failure",
        "--- stdout (tail) ---",
        "Error: compilation failed",
    ]
    save_state(s, store.state_path(str(ws)))
    return ws


def _run_romyq(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "romyq.cli"] + list(args),
        cwd=cwd,
        capture_output=True,
        text=True,
    )


# ── status --json ─────────────────────────────────────────────────────────────

class TestStatusJson:

    def test_outputs_valid_json(self, workspace):
        result = _run_romyq("status", "--json", str(workspace), cwd=workspace)
        assert result.returncode == 0
        parsed = json.loads(result.stdout)
        assert isinstance(parsed, dict)

    def test_json_contains_required_fields(self, workspace):
        result = _run_romyq("status", "--json", str(workspace), cwd=workspace)
        data = json.loads(result.stdout)
        for key in ("status", "phase", "tasks_completed", "heartbeat", "last_commit",
                    "current_task_attempts", "consecutive_failures", "max_task_attempts"):
            assert key in data, f"Missing key: {key}"

    def test_json_round_trips_state(self, workspace_with_failures):
        result = _run_romyq("status", "--json", str(workspace_with_failures), cwd=workspace_with_failures)
        data = json.loads(result.stdout)
        assert data["current_task_attempts"] == 2
        assert data["last_failure_reason"] == "Claude exited with non-zero status"
        assert data["tasks_completed"] == 3
        assert data["last_commit"] == "abc1234"

    def test_json_output_does_not_contain_human_headers(self, workspace):
        result = _run_romyq("status", "--json", str(workspace), cwd=workspace)
        assert "Workspace:" not in result.stdout
        assert "Status:" not in result.stdout

    def test_json_includes_validation_evidence(self, workspace_with_failures):
        result = _run_romyq("status", "--json", str(workspace_with_failures), cwd=workspace_with_failures)
        data = json.loads(result.stdout)
        assert isinstance(data["last_validation_evidence"], list)
        assert any("exit_code" in e for e in data["last_validation_evidence"])

    def test_status_without_json_flag_is_human_readable(self, workspace):
        result = _run_romyq("status", str(workspace), cwd=workspace)
        assert "Status:" in result.stdout or "status" in result.stdout.lower()
        with pytest.raises(json.JSONDecodeError):
            json.loads(result.stdout)


# ── romyq explain ─────────────────────────────────────────────────────────────

class TestExplainCommand:

    def test_explain_exits_zero_on_valid_workspace(self, workspace):
        result = _run_romyq("explain", str(workspace), cwd=workspace)
        assert result.returncode == 0

    def test_explain_shows_phase(self, workspace_with_failures):
        result = _run_romyq("explain", str(workspace_with_failures), cwd=workspace_with_failures)
        assert "idle" in result.stdout

    def test_explain_shows_task_text(self, workspace_with_failures):
        result = _run_romyq("explain", str(workspace_with_failures), cwd=workspace_with_failures)
        assert "authentication module" in result.stdout

    def test_explain_shows_attempt_count(self, workspace_with_failures):
        result = _run_romyq("explain", str(workspace_with_failures), cwd=workspace_with_failures)
        assert "2" in result.stdout  # 2 attempts
        assert "3" in result.stdout  # ceiling of 3

    def test_explain_shows_last_failure_reason(self, workspace_with_failures):
        result = _run_romyq("explain", str(workspace_with_failures), cwd=workspace_with_failures)
        assert "non-zero" in result.stdout

    def test_explain_shows_validation_evidence(self, workspace_with_failures):
        result = _run_romyq("explain", str(workspace_with_failures), cwd=workspace_with_failures)
        assert "exit_code=1" in result.stdout
        assert "compilation failed" in result.stdout

    def test_explain_clean_state_shows_none_sections(self, workspace):
        result = _run_romyq("explain", str(workspace), cwd=workspace)
        assert "(none)" in result.stdout

    def test_explain_shows_blocked_when_at_ceiling(self, tmp_path):
        ws = tmp_path / "ws"
        ws.mkdir()
        store.ensure_dir(str(ws))
        s = DEFAULT_STATE.copy()
        s["max_task_attempts"] = 2
        s["current_task"] = "A task"
        record_task_failure(s, "blocked_key", "error 1")
        record_task_failure(s, "blocked_key", "error 2")
        save_state(s, store.state_path(str(ws)))

        result = _run_romyq("explain", str(ws), cwd=ws)
        assert "BLOCKED" in result.stdout

    def test_explain_shows_section_headers(self, workspace):
        result = _run_romyq("explain", str(workspace), cwd=workspace)
        assert "Loop State" in result.stdout
        assert "Current Task" in result.stdout
        assert "Failure Tracking" in result.stdout
        assert "Validation Evidence" in result.stdout

    def test_explain_exits_nonzero_on_missing_workspace(self, tmp_path):
        result = _run_romyq("explain", str(tmp_path / "nonexistent"), cwd=tmp_path)
        assert result.returncode != 0
