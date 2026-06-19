"""Tests for romyq CLI — romyq knowledge, romyq patterns, and enhanced romyq planning."""
from __future__ import annotations

import json
import argparse
from datetime import datetime, timezone
from pathlib import Path

import pytest

from romyq import memory as mem_mod
from romyq import knowledge as know_mod


# ── fixtures ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: str, data) -> None:
    Path(path).write_text(json.dumps(data), encoding="utf-8")


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
    _write_json(str(romyq_dir / "history.json"), [])
    _write_json(str(romyq_dir / "findings.json"), [])
    (romyq_dir / "events.log").write_text("", encoding="utf-8")
    _write_json(str(romyq_dir / "memory.json"), {"entries": [], "missions": {}})
    return tmp_path


def _invoke_knowledge(workspace, args=None):
    from romyq.cli import cmd_knowledge
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", nargs="?", default=None)
    parser.add_argument("--json", action="store_true", default=False)
    parsed = parser.parse_args([str(workspace)] + (args or []))
    cmd_knowledge(parsed)


def _invoke_patterns(workspace, args=None):
    from romyq.cli import cmd_patterns
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", nargs="?", default=None)
    parser.add_argument("--json", action="store_true", default=False)
    parsed = parser.parse_args([str(workspace)] + (args or []))
    cmd_patterns(parsed)


def _invoke_planning(workspace, args=None):
    from romyq.cli import cmd_planning
    parser = argparse.ArgumentParser()
    parser.add_argument("workspace", nargs="?", default=None)
    parser.add_argument("--json", action="store_true", default=False)
    parsed = parser.parse_args([str(workspace)] + (args or []))
    cmd_planning(parsed)


def _write_knowledge(workspace, lessons=None, patterns=None, stale=False):
    know_path = workspace / ".romyq" / "knowledge.json"
    h = know_mod._structure_hash("", 0, 0)
    _write_json(str(know_path), {
        "version": 1,
        "generated_at": _now_iso(),
        "structure_hash": "stale_hash" if stale else h,
        "patterns": patterns or [],
        "lessons": lessons or [],
    })


# ── TestKnowledgeCommand ──────────────────────────────────────────────────────

class TestKnowledgeCommand:
    def test_basic_output(self, workspace, capsys):
        _invoke_knowledge(workspace)
        out = capsys.readouterr().out
        assert "romyq knowledge" in out

    def test_shows_knowledge_base_section(self, workspace, capsys):
        _invoke_knowledge(workspace)
        out = capsys.readouterr().out
        assert "Knowledge Base" in out

    def test_shows_lessons_section(self, workspace, capsys):
        _invoke_knowledge(workspace)
        out = capsys.readouterr().out
        assert "Lessons" in out or "lesson" in out.lower()

    def test_shows_failure_patterns_section(self, workspace, capsys):
        _invoke_knowledge(workspace)
        out = capsys.readouterr().out
        assert "Failure Patterns" in out or "failure" in out.lower()

    def test_shows_absent_status_when_no_knowledge(self, workspace, capsys):
        _invoke_knowledge(workspace)
        out = capsys.readouterr().out
        assert "absent" in out.lower() or "not yet generated" in out.lower() or "romyq run" in out

    def test_shows_lessons_when_present(self, workspace, capsys):
        _write_knowledge(workspace, lessons=["Use smaller tasks", "Fix linting first"])
        _invoke_knowledge(workspace)
        out = capsys.readouterr().out
        assert "Use smaller tasks" in out

    def test_shows_failure_patterns_when_present(self, workspace, capsys):
        patterns = [{"type": "failure_pattern", "fingerprint": "abc123",
                     "task_preview": "Add JWT auth", "count": 3, "last_reason": "ImportError"}]
        _write_knowledge(workspace, patterns=patterns)
        _invoke_knowledge(workspace)
        out = capsys.readouterr().out
        assert "Add JWT auth" in out or "3" in out

    def test_json_output_structure(self, workspace, capsys):
        _invoke_knowledge(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "generated_at" in data
        assert "stale" in data
        assert "lesson_count" in data
        assert "lessons" in data
        assert "failure_patterns" in data
        assert "success_patterns" in data

    def test_json_lessons_is_list(self, workspace, capsys):
        _invoke_knowledge(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data["lessons"], list)

    def test_json_lesson_count_zero_when_empty(self, workspace, capsys):
        _invoke_knowledge(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["lesson_count"] == 0

    def test_json_lesson_count_matches_lessons(self, workspace, capsys):
        _write_knowledge(workspace, lessons=["A", "B", "C"])
        _invoke_knowledge(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["lesson_count"] == len(data["lessons"])

    def test_json_stale_true_when_absent(self, workspace, capsys):
        _invoke_knowledge(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["stale"] is True

    def test_json_stale_false_when_fresh(self, workspace, capsys):
        _write_knowledge(workspace)
        _invoke_knowledge(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["stale"] is False

    def test_workspace_not_found(self, tmp_path, capsys):
        from romyq.cli import cmd_knowledge
        parser = argparse.ArgumentParser()
        parser.add_argument("workspace", nargs="?", default=None)
        parser.add_argument("--json", action="store_true", default=False)
        parsed = parser.parse_args([str(tmp_path / "nonexistent")])
        with pytest.raises(SystemExit):
            cmd_knowledge(parsed)

    def test_shows_success_patterns_section(self, workspace, capsys):
        _invoke_knowledge(workspace)
        out = capsys.readouterr().out
        assert "Success Patterns" in out


# ── TestPatternsCommand ───────────────────────────────────────────────────────

class TestPatternsCommand:
    def test_basic_output(self, workspace, capsys):
        _invoke_patterns(workspace)
        out = capsys.readouterr().out
        assert "romyq patterns" in out

    def test_shows_failure_patterns_section(self, workspace, capsys):
        _invoke_patterns(workspace)
        out = capsys.readouterr().out
        assert "Failure Patterns" in out

    def test_shows_success_patterns_section(self, workspace, capsys):
        _invoke_patterns(workspace)
        out = capsys.readouterr().out
        assert "Success Patterns" in out

    def test_shows_no_patterns_when_empty(self, workspace, capsys):
        _invoke_patterns(workspace)
        out = capsys.readouterr().out
        assert "No failure patterns" in out or "None" in out

    def test_shows_failure_pattern_when_present(self, workspace, capsys):
        patterns = [{"type": "failure_pattern", "fingerprint": "abc123",
                     "task_preview": "Add OAuth integration", "count": 4,
                     "last_reason": "timeout"}]
        _write_knowledge(workspace, patterns=patterns)
        _invoke_patterns(workspace)
        out = capsys.readouterr().out
        assert "Add OAuth integration" in out or "4" in out

    def test_shows_success_pattern_when_present(self, workspace, capsys):
        patterns = [{"type": "success_pattern", "fingerprint": "def456",
                     "task_preview": "Add unit tests", "count": 6}]
        _write_knowledge(workspace, patterns=patterns)
        _invoke_patterns(workspace)
        out = capsys.readouterr().out
        assert "Add unit tests" in out or "6" in out

    def test_json_output_structure(self, workspace, capsys):
        _invoke_patterns(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "generated_at" in data
        assert "total_patterns" in data
        assert "failure_patterns" in data
        assert "success_patterns" in data

    def test_json_failure_patterns_is_list(self, workspace, capsys):
        _invoke_patterns(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data["failure_patterns"], list)

    def test_json_success_patterns_is_list(self, workspace, capsys):
        _invoke_patterns(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data["success_patterns"], list)

    def test_json_total_patterns_zero_when_empty(self, workspace, capsys):
        _invoke_patterns(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["total_patterns"] == 0

    def test_workspace_not_found(self, tmp_path, capsys):
        from romyq.cli import cmd_patterns
        parser = argparse.ArgumentParser()
        parser.add_argument("workspace", nargs="?", default=None)
        parser.add_argument("--json", action="store_true", default=False)
        parsed = parser.parse_args([str(tmp_path / "nonexistent")])
        with pytest.raises(SystemExit):
            cmd_patterns(parsed)

    def test_failure_patterns_sorted_in_output(self, workspace, capsys):
        patterns = [
            {"type": "failure_pattern", "fingerprint": "a", "task_preview": "Low count task",
             "count": 1, "last_reason": "error"},
            {"type": "failure_pattern", "fingerprint": "b", "task_preview": "High count task",
             "count": 9, "last_reason": "timeout"},
        ]
        _write_knowledge(workspace, patterns=patterns)
        _invoke_patterns(workspace)
        out = capsys.readouterr().out
        # High count should appear before low count
        high_pos = out.find("High count task")
        low_pos = out.find("Low count task")
        if high_pos >= 0 and low_pos >= 0:
            assert high_pos < low_pos


# ── TestPlanningEnhancedSections ──────────────────────────────────────────────

class TestPlanningEnhancedSections:
    def test_shows_memory_signals_section(self, workspace, capsys):
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "Memory Signals" in out

    def test_shows_knowledge_signals_section(self, workspace, capsys):
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "Knowledge Signals" in out

    def test_shows_repository_signals_section(self, workspace, capsys):
        _invoke_planning(workspace)
        out = capsys.readouterr().out
        assert "Repository Signals" in out

    def test_json_includes_memory_signals(self, workspace, capsys):
        _invoke_planning(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "memory_signals" in data
        assert "success_rate" in data["memory_signals"]
        assert "retry_rate" in data["memory_signals"]

    def test_json_includes_knowledge_signals(self, workspace, capsys):
        _invoke_planning(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "knowledge_signals" in data
        assert "fresh" in data["knowledge_signals"]
        assert "lesson_count" in data["knowledge_signals"]

    def test_json_includes_repository_signals(self, workspace, capsys):
        _invoke_planning(workspace, args=["--json"])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "repository_signals" in data
        assert "context_present" in data["repository_signals"]
