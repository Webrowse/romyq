"""Tests for romyq CLI — romyq timeline and romyq stats commands."""
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso(delta_s: int = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(seconds=delta_s)
    return dt.replace(microsecond=0).isoformat()


def _write_events(path: str, entries: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")


def _write_history(path: str, entries: list[dict]) -> None:
    Path(path).write_text(json.dumps(entries), encoding="utf-8")


def _write_state(path: str, state: dict) -> None:
    Path(path).write_text(json.dumps(state), encoding="utf-8")


def _default_state() -> dict:
    return {
        "status": "running",
        "phase": "idle",
        "tasks_completed": 5,
        "last_commit": "abc1234",
        "heartbeat": _now_iso(-30),
        "audit_interval": 10,
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
    }


@pytest.fixture()
def workspace(tmp_path):
    romyq_dir = tmp_path / ".romyq"
    romyq_dir.mkdir()
    state_path = romyq_dir / "state.json"
    history_path = romyq_dir / "history.json"
    events_path = romyq_dir / "events.log"
    state_path.write_text(json.dumps(_default_state()), encoding="utf-8")
    history_path.write_text(json.dumps([]), encoding="utf-8")
    events_path.write_text("", encoding="utf-8")
    return tmp_path


# ── romyq timeline ────────────────────────────────────────────────────────────

class TestTimeline:
    def _invoke(self, workspace, args=None, capsys=None):
        from romyq.cli import cmd_timeline
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("workspace", nargs="?", default=None)
        parser.add_argument("--last", type=int, default=50)
        parser.add_argument("--json", action="store_true", default=False)
        parsed = parser.parse_args([str(workspace)] + (args or []))
        cmd_timeline(parsed)

    def test_no_events_prints_message(self, workspace, capsys):
        self._invoke(workspace, capsys=capsys)
        captured = capsys.readouterr()
        assert "No events" in captured.out

    def test_shows_events(self, workspace, capsys):
        e_path = workspace / ".romyq" / "events.log"
        _write_events(str(e_path), [
            {"ts": _now_iso(-100), "event": "loop_started"},
            {"ts": _now_iso(-50), "event": "task_completed", "key": "abc123"},
            {"ts": _now_iso(), "event": "loop_stopped", "reason": "stop_requested"},
        ])
        self._invoke(workspace, capsys=capsys)
        captured = capsys.readouterr()
        assert "loop_started" in captured.out.lower() or "Loop started" in captured.out
        assert "loop_stopped" in captured.out.lower() or "Loop stopped" in captured.out

    def test_json_output(self, workspace, capsys):
        e_path = workspace / ".romyq" / "events.log"
        _write_events(str(e_path), [
            {"ts": _now_iso(-10), "event": "loop_started"},
        ])
        self._invoke(workspace, args=["--json"], capsys=capsys)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert isinstance(data, list)
        assert data[0]["event"] == "loop_started"

    def test_last_flag_limits_events(self, workspace, capsys):
        e_path = workspace / ".romyq" / "events.log"
        _write_events(str(e_path), [
            {"ts": _now_iso(-i*10), "event": "task_started", "key": f"k{i}"}
            for i in range(20)
        ])
        self._invoke(workspace, args=["--last", "5"], capsys=capsys)
        captured = capsys.readouterr()
        # 5 events max; each line has a timestamp
        lines = [l for l in captured.out.splitlines() if "[" in l]
        assert len(lines) <= 5

    def test_shows_human_labels(self, workspace, capsys):
        e_path = workspace / ".romyq" / "events.log"
        _write_events(str(e_path), [
            {"ts": _now_iso(), "event": "validator_failed", "reason": "tests failed"},
        ])
        self._invoke(workspace, capsys=capsys)
        captured = capsys.readouterr()
        assert "Validator failed" in captured.out or "validator_failed" in captured.out

    def test_workspace_not_found(self, tmp_path, capsys):
        from romyq.cli import cmd_timeline
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("workspace", nargs="?", default=None)
        parser.add_argument("--last", type=int, default=50)
        parser.add_argument("--json", action="store_true", default=False)
        parsed = parser.parse_args([str(tmp_path / "nonexistent")])
        with pytest.raises(SystemExit):
            cmd_timeline(parsed)


# ── romyq stats ───────────────────────────────────────────────────────────────

class TestStats:
    def _invoke(self, workspace, args=None, capsys=None):
        from romyq.cli import cmd_stats
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("workspace", nargs="?", default=None)
        parser.add_argument("--json", action="store_true", default=False)
        parsed = parser.parse_args([str(workspace)] + (args or []))
        cmd_stats(parsed)

    def test_basic_output(self, workspace, capsys):
        self._invoke(workspace, capsys=capsys)
        captured = capsys.readouterr()
        assert "Tasks completed" in captured.out
        assert "Runtime" in captured.out

    def test_json_output_structure(self, workspace, capsys):
        self._invoke(workspace, args=["--json"], capsys=capsys)
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "tasks_completed" in data
        assert "validator_pass_rate" in data
        assert "runtime_hours" in data
        assert "event_count" in data

    def test_shows_pass_rate_na_when_empty(self, workspace, capsys):
        self._invoke(workspace, capsys=capsys)
        captured = capsys.readouterr()
        assert "n/a" in captured.out

    def test_shows_pass_rate_percentage(self, workspace, capsys):
        h_path = workspace / ".romyq" / "history.json"
        _write_history(str(h_path), [
            {"task": "t", "success": True, "timestamp": _now_iso(),
             "mode": "impl", "commit": "a", "validation_reason": "ok"},
        ])
        self._invoke(workspace, capsys=capsys)
        captured = capsys.readouterr()
        assert "100.0%" in captured.out

    def test_stats_from_events(self, workspace, capsys):
        e_path = workspace / ".romyq" / "events.log"
        _write_events(str(e_path), [
            {"ts": _now_iso(-i), "event": "rate_limit_detected"} for i in range(3)
        ])
        self._invoke(workspace, capsys=capsys)
        captured = capsys.readouterr()
        assert "Rate-limit" in captured.out

    def test_workspace_not_found(self, tmp_path, capsys):
        from romyq.cli import cmd_stats
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument("workspace", nargs="?", default=None)
        parser.add_argument("--json", action="store_true", default=False)
        parsed = parser.parse_args([str(tmp_path / "nonexistent")])
        with pytest.raises(SystemExit):
            cmd_stats(parsed)
