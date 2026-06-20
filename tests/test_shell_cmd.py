"""Tests for romyq/shell.py — operator REPL."""
from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from romyq import store
from romyq.shell import (
    BUILTIN_COMMANDS,
    parse_command,
    is_builtin,
    dispatch,
    run_shell,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_workspace(tmp_path: Path) -> str:
    ws = str(tmp_path)
    store.ensure_dir(ws)
    return ws


def _write_lifecycle(ws: str) -> None:
    lc = {
        "phases": [
            {
                "id": 1,
                "name": "Foundation",
                "status": "active",
                "percentage_complete": 0,
                "total_tasks": 2,
                "completed_tasks": 0,
                "tasks": [
                    {"id": "t1", "text": "Setup project structure", "status": "active"},
                    {"id": "t2", "text": "Configure dependencies", "status": "pending"},
                ],
            },
        ],
        "done_criteria": [],
        "mission": "Test",
    }
    with open(store.lifecycle_path(ws), "w") as f:
        json.dump(lc, f)


def _write_state(ws: str, paused=False, stopped=False) -> None:
    from romyq.state import save as save_state, load as load_state
    try:
        state = load_state(store.state_path(ws))
    except Exception:
        state = {
            "status": "running",
            "phase": "planning",
            "tasks_completed": 0,
            "last_commit": None,
            "heartbeat": None,
            "current_task": "",
            "audit_interval": 5,
            "paused": paused,
            "stop_requested": stopped,
        }
    state["paused"] = paused
    state["stop_requested"] = stopped
    save_state(state, store.state_path(ws))


# ── BUILTIN_COMMANDS ──────────────────────────────────────────────────────────

class TestBuiltinCommands:
    def test_status_is_builtin(self):
        assert "status" in BUILTIN_COMMANDS

    def test_roadmap_is_builtin(self):
        assert "roadmap" in BUILTIN_COMMANDS

    def test_phase_is_builtin(self):
        assert "phase" in BUILTIN_COMMANDS

    def test_capabilities_is_builtin(self):
        assert "capabilities" in BUILTIN_COMMANDS

    def test_readiness_is_builtin(self):
        assert "readiness" in BUILTIN_COMMANDS

    def test_recommendation_is_builtin(self):
        assert "recommendation" in BUILTIN_COMMANDS

    def test_pause_is_builtin(self):
        assert "pause" in BUILTIN_COMMANDS

    def test_resume_is_builtin(self):
        assert "resume" in BUILTIN_COMMANDS

    def test_stop_is_builtin(self):
        assert "stop" in BUILTIN_COMMANDS

    def test_rules_is_builtin(self):
        assert "rules" in BUILTIN_COMMANDS

    def test_knowledge_is_builtin(self):
        assert "knowledge" in BUILTIN_COMMANDS

    def test_help_is_builtin(self):
        assert "help" in BUILTIN_COMMANDS

    def test_exit_is_builtin(self):
        assert "exit" in BUILTIN_COMMANDS

    def test_quit_is_builtin(self):
        assert "quit" in BUILTIN_COMMANDS

    def test_dashboard_is_builtin(self):
        assert "dashboard" in BUILTIN_COMMANDS

    def test_is_frozenset(self):
        assert isinstance(BUILTIN_COMMANDS, frozenset)


# ── parse_command ─────────────────────────────────────────────────────────────

class TestParseCommand:
    def test_empty_returns_empty_tuple(self):
        cmd, args = parse_command("")
        assert cmd == ""
        assert args == []

    def test_whitespace_only_returns_empty(self):
        cmd, args = parse_command("   ")
        assert cmd == ""
        assert args == []

    def test_single_word_command(self):
        cmd, args = parse_command("status")
        assert cmd == "status"
        assert args == []

    def test_command_with_args(self):
        cmd, args = parse_command("lifecycle show")
        assert cmd == "lifecycle"
        assert args == ["show"]

    def test_command_lowercased(self):
        cmd, args = parse_command("STATUS")
        assert cmd == "status"

    def test_leading_whitespace_stripped(self):
        cmd, args = parse_command("  status  ")
        assert cmd == "status"

    def test_multi_word_args_split(self):
        cmd, args = parse_command("capabilities set auth complete")
        assert cmd == "capabilities"
        assert "set" in args

    def test_free_text_first_word_is_cmd(self):
        cmd, _ = parse_command("use PostgreSQL for the database")
        assert cmd == "use"


# ── is_builtin ────────────────────────────────────────────────────────────────

class TestIsBuiltin:
    def test_status_is_builtin(self):
        assert is_builtin("status")

    def test_roadmap_is_builtin(self):
        assert is_builtin("roadmap")

    def test_free_text_not_builtin(self):
        assert not is_builtin("use PostgreSQL")

    def test_empty_not_builtin(self):
        assert not is_builtin("")

    def test_whitespace_not_builtin(self):
        assert not is_builtin("   ")

    def test_partial_match_not_builtin(self):
        assert not is_builtin("stat")


# ── dispatch ──────────────────────────────────────────────────────────────────

class TestDispatch:
    def test_empty_line_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("", ws, out=io.StringIO()) is True

    def test_exit_returns_false(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("exit", ws, out=io.StringIO()) is False

    def test_quit_returns_false(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("quit", ws, out=io.StringIO()) is False

    def test_help_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("help", ws, out=io.StringIO()) is True

    def test_help_outputs_something(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        dispatch("help", ws, out=out)
        assert len(out.getvalue()) > 0

    def test_status_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_state(ws)
        assert dispatch("status", ws, out=io.StringIO()) is True

    def test_roadmap_no_crash_without_lifecycle(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        assert dispatch("roadmap", ws, out=out) is True

    def test_roadmap_shows_phases_when_lifecycle_present(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws)
        out = io.StringIO()
        dispatch("roadmap", ws, out=out)
        assert "Foundation" in out.getvalue()

    def test_phase_no_crash_without_lifecycle(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        assert dispatch("phase", ws, out=out) is True

    def test_recommendation_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("recommendation", ws, out=io.StringIO()) is True

    def test_readiness_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("readiness", ws, out=io.StringIO()) is True

    def test_capabilities_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("capabilities", ws, out=io.StringIO()) is True

    def test_rules_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("rules", ws, out=io.StringIO()) is True

    def test_knowledge_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("knowledge", ws, out=io.StringIO()) is True

    def test_free_text_recorded_as_instruction(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        with patch("romyq.notes.append") as mock_append:
            dispatch("use PostgreSQL for the database", ws, out=out)
            mock_append.assert_called_once()

    def test_free_text_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        with patch("romyq.notes.append"):
            result = dispatch("focus on security", ws, out=io.StringIO())
        assert result is True

    def test_dashboard_returns_true(self, tmp_path):
        ws = _make_workspace(tmp_path)
        assert dispatch("dashboard", ws, out=io.StringIO()) is True


# ── pause / resume / stop handlers ───────────────────────────────────────────

class TestPauseResumeStop:
    def test_pause_sets_paused_flag(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_state(ws, paused=False)
        out = io.StringIO()
        dispatch("pause", ws, out=out)
        from romyq.state import load as load_state
        state = load_state(store.state_path(ws))
        assert state.get("paused") is True

    def test_pause_already_paused_message(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_state(ws, paused=True)
        out = io.StringIO()
        dispatch("pause", ws, out=out)
        assert "paused" in out.getvalue().lower()

    def test_resume_clears_paused_flag(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_state(ws, paused=True)
        out = io.StringIO()
        dispatch("resume", ws, out=out)
        from romyq.state import load as load_state
        state = load_state(store.state_path(ws))
        assert state.get("paused") is False

    def test_resume_when_not_paused_message(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_state(ws, paused=False)
        out = io.StringIO()
        dispatch("resume", ws, out=out)
        assert "not paused" in out.getvalue().lower()

    def test_stop_sets_stop_requested(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_state(ws, stopped=False)
        out = io.StringIO()
        dispatch("stop", ws, out=out)
        from romyq.state import load as load_state
        state = load_state(store.state_path(ws))
        assert state.get("stop_requested") is True

    def test_stop_already_requested_message(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_state(ws, stopped=True)
        out = io.StringIO()
        dispatch("stop", ws, out=out)
        assert "stop" in out.getvalue().lower()


# ── run_shell ─────────────────────────────────────────────────────────────────

class TestRunShell:
    def test_exits_on_exit_command(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        inputs = iter(["exit"])
        run_shell(ws, _input_fn=lambda _: next(inputs), out=out)
        # Should complete without hanging

    def test_exits_on_eof(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        def raise_eof(_):
            raise EOFError
        run_shell(ws, _input_fn=raise_eof, out=out)
        # Should complete gracefully

    def test_exits_on_keyboard_interrupt(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        def raise_interrupt(_):
            raise KeyboardInterrupt
        run_shell(ws, _input_fn=raise_interrupt, out=out)

    def test_prints_welcome_message(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        inputs = iter(["exit"])
        run_shell(ws, _input_fn=lambda _: next(inputs), out=out)
        result = out.getvalue()
        assert "Romyq" in result or "shell" in result.lower()

    def test_processes_help_command(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        inputs = iter(["help", "exit"])
        run_shell(ws, _input_fn=lambda _: next(inputs), out=out)
        result = out.getvalue()
        assert "status" in result

    def test_records_free_text_instruction(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        inputs = iter(["use Redis for caching", "exit"])
        with patch("romyq.notes.append") as mock_append:
            run_shell(ws, _input_fn=lambda _: next(inputs), out=out)
            mock_append.assert_called_once()

    def test_processes_multiple_commands(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        inputs = iter(["help", "readiness", "exit"])
        run_shell(ws, _input_fn=lambda _: next(inputs), out=out)
        result = out.getvalue()
        assert len(result) > 0
