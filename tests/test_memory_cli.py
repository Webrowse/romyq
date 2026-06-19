"""Tests for romyq CLI — romyq planning and romyq memory commands."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from romyq import memory as mem_mod


# ── fixtures ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_state(path: str, **kwargs) -> None:
    state = {
        "status": "running",
        "phase": "idle",
        "tasks_completed": 0,
        "last_commit": "",
        "heartbeat": _now_iso(),
        "audit_interval": 5,
        "last_audit": 0,
        "current_task": "",
        "current_task_key": "",
        "current_task_attempts": 0,
        "max_task_attempts": 3,
        "consecutive_failures": 0,
        "last_failure_reason": "",
        "last_failure_timestamp": "",
        "last_validation_evidence": [],
        "paused": False,
        "stop_requested": False,
        "resume_at": "",
        "provider": "",
    }
    state.update(kwargs)
    Path(path).write_text(json.dumps(state), encoding="utf-8")


@pytest.fixture()
def workspace(tmp_path):
    romyq_dir = tmp_path / ".romyq"
    romyq_dir.mkdir()
    _write_state(str(romyq_dir / "state.json"))
    (romyq_dir / "history.json").write_text("[]", encoding="utf-8")
    (romyq_dir / "findings.json").write_text("[]", encoding="utf-8")
    (romyq_dir / "events.log").write_text("", encoding="utf-8")
    return tmp_path


def _invoke_planning(workspace, args=None):
    from romyq.cli import cmd_planning
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", nargs="?", default=None)
    parser.add_argument("--json", action="store_true", default=False)
    parsed = parser.parse_args([str(workspace)] + (args or []))
    cmd_planning(parsed)


def _invoke_memory(workspace, args=None):
    from romyq.cli import cmd_memory
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", nargs="?", default=None)
    parser.add_argument("--json", action="store_true", default=False)
    parsed = parser.parse_args([str(workspace)] + (args or []))
    cmd_memory(parsed)


# ── romyq planning ────────────────────────────────────────────────────────────

class TestPlanningCommand:
    def test_basic_output(self, workspace, capsys):
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "romyq planning" in out

    def test_shows_repository_memory_section(self, workspace, capsys):
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "Repository Memory" in out

    def test_shows_planner_loop_section(self, workspace, capsys):
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "Planner Loop" in out

    def test_shows_no_loops_when_healthy(self, workspace, capsys):
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "No loops detected" in out

    def test_shows_loop_warning_when_cycling(self, workspace, capsys):
        mem_path = str(workspace / ".romyq" / "memory.json")
        for _ in range(4):
            mem_mod.record(
                path=mem_path,
                task="Add health endpoint",
                mission_fp="mfp1",
                outcome="FAILURE",
                evidence=[],
                failure_reason="route not found",
                retry_count=1,
            )
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "!" in out or "same task" in out.lower() or "repeated" in out.lower()

    def test_shows_blocked_task_section(self, workspace, capsys):
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "Blocked Task" in out

    def test_json_output_structure(self, workspace, capsys):
        _invoke_planning(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "planning_context" in data
        assert "planner_loops" in data
        assert "repeated_task_warnings" in data
        assert "blocked_task" in data

    def test_json_blocked_task_has_fields(self, workspace, capsys):
        _invoke_planning(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        bt = data["blocked_task"]
        assert "key" in bt
        assert "attempts" in bt
        assert "ceiling" in bt

    def test_workspace_not_found(self, tmp_path, capsys):
        from romyq.cli import cmd_planning
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("workspace", nargs="?", default=None)
        parser.add_argument("--json", action="store_true", default=False)
        parsed = parser.parse_args([str(tmp_path / "nonexistent")])
        with pytest.raises(SystemExit):
            cmd_planning(parsed)

    def test_repeated_task_warnings_section(self, workspace, capsys):
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "Repeated Task" in out

    def test_json_loops_is_list(self, workspace, capsys):
        _invoke_planning(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data["planner_loops"], list)


# ── romyq memory ─────────────────────────────────────────────────────────────

class TestMemoryCommand:
    def test_basic_output(self, workspace, capsys):
        _invoke_memory(workspace)
        out = capsys.readouterr().out
        assert "romyq memory" in out

    def test_shows_summary_section(self, workspace, capsys):
        _invoke_memory(workspace)
        out = capsys.readouterr().out
        assert "Summary" in out

    def test_shows_most_failed_section(self, workspace, capsys):
        _invoke_memory(workspace)
        out = capsys.readouterr().out
        assert "Most Failed" in out

    def test_shows_planner_loop_section(self, workspace, capsys):
        _invoke_memory(workspace)
        out = capsys.readouterr().out
        assert "Planner Loop" in out

    def test_shows_mission_section(self, workspace, capsys):
        _invoke_memory(workspace)
        out = capsys.readouterr().out
        assert "Mission" in out

    def test_shows_failed_task(self, workspace, capsys):
        mem_path = str(workspace / ".romyq" / "memory.json")
        mem_mod.record(
            path=mem_path,
            task="Fix broken authentication module",
            mission_fp="mfp1",
            outcome="FAILURE",
            evidence=["exit code: 1"],
            failure_reason="ImportError jwt",
            retry_count=1,
        )
        _invoke_memory(workspace)
        out = capsys.readouterr().out
        assert "Fix broken authentication" in out or "authentication" in out.lower()

    def test_json_output_structure(self, workspace, capsys):
        _invoke_memory(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "total_entries" in data
        assert "success_rate" in data
        assert "most_failed" in data
        assert "planner_loops" in data
        assert "mission_outcomes" in data

    def test_json_most_failed_is_list(self, workspace, capsys):
        _invoke_memory(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data["most_failed"], list)

    def test_json_total_entries_zero_when_empty(self, workspace, capsys):
        _invoke_memory(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["total_entries"] == 0

    def test_json_success_rate_after_recording(self, workspace, capsys):
        mem_path = str(workspace / ".romyq" / "memory.json")
        mem_mod.record(
            path=mem_path, task="task a", mission_fp="m1", outcome="SUCCESS",
            evidence=[], failure_reason="", retry_count=0,
        )
        mem_mod.record(
            path=mem_path, task="task b", mission_fp="m1", outcome="FAILURE",
            evidence=[], failure_reason="error", retry_count=1,
        )
        _invoke_memory(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["success_rate"] == 0.5

    def test_workspace_not_found(self, tmp_path, capsys):
        from romyq.cli import cmd_memory
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("workspace", nargs="?", default=None)
        parser.add_argument("--json", action="store_true", default=False)
        parsed = parser.parse_args([str(tmp_path / "nonexistent")])
        with pytest.raises(SystemExit):
            cmd_memory(parsed)

    def test_shows_none_in_sections_when_empty(self, workspace, capsys):
        _invoke_memory(workspace)
        out = capsys.readouterr().out
        assert "None" in out or "No " in out
