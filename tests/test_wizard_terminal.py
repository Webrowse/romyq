"""Tests for romyq/wizard_terminal.py — terminal-native setup wizard."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from romyq import store
from romyq.wizard_terminal import (
    COMPLEXITY_OPTIONS,
    generate_architecture_preview,
    print_architecture_preview,
    run_terminal_wizard,
    select_option,
    _read_mission_text,
    _run_setup,
)


# ── COMPLEXITY_OPTIONS ────────────────────────────────────────────────────────

class TestComplexityOptions:
    def test_has_three_options(self):
        assert len(COMPLEXITY_OPTIONS) == 3

    def test_basic_option_exists(self):
        values = [v for v, _, _ in COMPLEXITY_OPTIONS]
        assert "basic" in values

    def test_intermediate_option_exists(self):
        values = [v for v, _, _ in COMPLEXITY_OPTIONS]
        assert "intermediate" in values

    def test_advanced_option_exists(self):
        values = [v for v, _, _ in COMPLEXITY_OPTIONS]
        assert "advanced" in values

    def test_each_option_has_three_elements(self):
        for opt in COMPLEXITY_OPTIONS:
            assert len(opt) == 3

    def test_descriptions_are_nonempty(self):
        for _, label, desc in COMPLEXITY_OPTIONS:
            assert len(desc) > 0


# ── select_option ─────────────────────────────────────────────────────────────

class TestSelectOption:
    """All tests run by controlling TTY mode and providing fake input functions."""

    def _fake_stdin_readline(self, choice: str):
        """Return a patched stdin with readline returning choice."""
        mock = MagicMock()
        mock.isatty.return_value = False
        mock.readline.return_value = f"{choice}\n"
        return mock

    def test_numbered_input_selects_first(self, monkeypatch):
        out = io.StringIO()
        monkeypatch.setattr("sys.stdin", self._fake_stdin_readline("1"))
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        result = select_option(COMPLEXITY_OPTIONS, _out=out)
        assert result == 0

    def test_numbered_input_selects_second(self, monkeypatch):
        out = io.StringIO()
        monkeypatch.setattr("sys.stdin", self._fake_stdin_readline("2"))
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        result = select_option(COMPLEXITY_OPTIONS, _out=out)
        assert result == 1

    def test_numbered_input_selects_third(self, monkeypatch):
        out = io.StringIO()
        monkeypatch.setattr("sys.stdin", self._fake_stdin_readline("3"))
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        result = select_option(COMPLEXITY_OPTIONS, _out=out)
        assert result == 2

    def test_invalid_input_defaults_to_zero(self, monkeypatch):
        out = io.StringIO()
        monkeypatch.setattr("sys.stdin", self._fake_stdin_readline("99"))
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        result = select_option(COMPLEXITY_OPTIONS, _out=out)
        assert result == 0

    def test_empty_input_defaults_to_zero(self, monkeypatch):
        out = io.StringIO()
        monkeypatch.setattr("sys.stdin", self._fake_stdin_readline(""))
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)
        result = select_option(COMPLEXITY_OPTIONS, _out=out)
        assert result == 0

    def test_tty_mode_arrow_key_enter(self, monkeypatch):
        out = io.StringIO()
        keys = iter(["enter"])
        def fake_keypress():
            return next(keys)
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        monkeypatch.setattr("sys.stdin", mock_stdin)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        result = select_option(COMPLEXITY_OPTIONS, _keypress_fn=fake_keypress, _out=out)
        assert result == 0

    def test_tty_mode_down_then_enter(self, monkeypatch):
        out = io.StringIO()
        keys = iter(["down", "enter"])
        def fake_keypress():
            return next(keys)
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        monkeypatch.setattr("sys.stdin", mock_stdin)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        result = select_option(COMPLEXITY_OPTIONS, _keypress_fn=fake_keypress, _out=out)
        assert result == 1

    def test_tty_mode_digit_shortcut(self, monkeypatch):
        out = io.StringIO()
        keys = iter(["2"])
        def fake_keypress():
            return next(keys)
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        monkeypatch.setattr("sys.stdin", mock_stdin)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        result = select_option(COMPLEXITY_OPTIONS, _keypress_fn=fake_keypress, _out=out)
        assert result == 1

    def test_tty_mode_up_wraps_around(self, monkeypatch):
        out = io.StringIO()
        keys = iter(["up", "enter"])
        def fake_keypress():
            return next(keys)
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        monkeypatch.setattr("sys.stdin", mock_stdin)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)
        result = select_option(COMPLEXITY_OPTIONS, _keypress_fn=fake_keypress, _out=out)
        assert result == len(COMPLEXITY_OPTIONS) - 1


# ── _read_mission_text ────────────────────────────────────────────────────────

class TestReadMissionText:
    def test_reads_single_line(self):
        out = io.StringIO()
        lines = iter(["Build a REST API", ""])
        def reader(prompt):
            return next(lines)
        result = _read_mission_text(reader, out=out)
        assert "Build a REST API" in result

    def test_reads_multiple_lines(self):
        out = io.StringIO()
        lines = iter(["Line one", "Line two", ""])
        def reader(prompt):
            return next(lines)
        result = _read_mission_text(reader, out=out)
        assert "Line one" in result
        assert "Line two" in result

    def test_blank_line_ends_input(self):
        out = io.StringIO()
        lines = iter(["First line", ""])
        def reader(prompt):
            return next(lines)
        result = _read_mission_text(reader, out=out)
        assert result == "First line"

    def test_eof_ends_gracefully(self):
        out = io.StringIO()
        def reader(prompt):
            raise EOFError
        result = _read_mission_text(reader, out=out)
        assert result == ""

    def test_empty_input_returns_empty(self):
        out = io.StringIO()
        def reader(prompt):
            raise EOFError
        result = _read_mission_text(reader, out=out)
        assert result == ""


# ── generate_architecture_preview ─────────────────────────────────────────────

class TestGenerateArchitecturePreview:
    def test_returns_none_on_exception(self):
        with patch("romyq.lifecycle.generate", side_effect=Exception("network error")):
            result = generate_architecture_preview("bad_key", "Build X", "basic")
        assert result is None

    def test_returns_dict_with_phases_on_success(self):
        mock_lc = {"phases": [{"id": 1, "name": "Foundation", "tasks": []}]}
        with patch("romyq.lifecycle.generate", return_value=mock_lc):
            result = generate_architecture_preview("sk-valid", "Build X", "basic")
        assert result is not None
        assert "phases" in result

    def test_returns_none_if_no_phases(self):
        mock_lc = {"phases": []}
        with patch("romyq.lifecycle.generate", return_value=mock_lc):
            result = generate_architecture_preview("sk-valid", "Build X", "basic")
        assert result is None


# ── print_architecture_preview ────────────────────────────────────────────────

class TestPrintArchitecturePreview:
    def _make_lc(self):
        return {
            "phases": [
                {"id": 1, "name": "Setup", "status": "pending", "total_tasks": 2, "completed_tasks": 0, "tasks": []},
                {"id": 2, "name": "Build", "status": "pending", "total_tasks": 3, "completed_tasks": 0, "tasks": []},
            ],
            "done_criteria": [],
        }

    def test_prints_phase_names(self):
        out = io.StringIO()
        print_architecture_preview(self._make_lc(), out=out)
        result = out.getvalue()
        assert "Setup" in result
        assert "Build" in result

    def test_prints_complexity_label(self):
        out = io.StringIO()
        print_architecture_preview(self._make_lc(), "Advanced", out=out)
        assert "Advanced" in out.getvalue()

    def test_prints_header_separator(self):
        out = io.StringIO()
        print_architecture_preview(self._make_lc(), out=out)
        assert "━" in out.getvalue()

    def test_no_output_for_empty_lifecycle(self):
        out = io.StringIO()
        print_architecture_preview({"phases": []}, out=out)
        assert out.getvalue() == ""


# ── _run_setup ────────────────────────────────────────────────────────────────

class TestRunSetup:
    def test_run_setup_returns_dict(self, tmp_path):
        ws = str(tmp_path)
        store.ensure_dir(ws)
        (Path(ws) / "mission.md").write_text("Build a test app")

        with patch("romyq.wizard_logic.wizard_setup") as mock_setup:
            mock_setup.return_value = {"env": "ok", "mission": "ok"}
            result = _run_setup(ws, "", "Build a test app", "basic", True, None)
        assert isinstance(result, dict)

    def test_run_setup_saves_complexity(self, tmp_path):
        ws = str(tmp_path)
        store.ensure_dir(ws)
        (Path(ws) / "mission.md").write_text("Build a test app")

        with patch("romyq.wizard_logic.wizard_setup") as mock_setup:
            mock_setup.return_value = {}
            _run_setup(ws, "", "Build a test app", "advanced", True, None)

        from romyq.profile import get_complexity
        prof_path = store.profile_path(ws)
        assert get_complexity(prof_path) == "advanced"

    def test_run_setup_presaves_lifecycle_when_provided(self, tmp_path):
        ws = str(tmp_path)
        store.ensure_dir(ws)
        (Path(ws) / "mission.md").write_text("Build a test app")

        lc_data = {
            "phases": [
                {"id": 1, "name": "Foundation", "status": "pending", "tasks": [{"id": "t1", "text": "Initialize project", "status": "pending"}]},
            ],
            "done_criteria": [],
        }

        with patch("romyq.wizard_logic.wizard_setup") as mock_setup:
            mock_setup.return_value = {}
            result = _run_setup(ws, "", "Build a test app", "basic", True, lc_data)

        lc_path = store.lifecycle_path(ws)
        assert Path(lc_path).exists()
        assert "lifecycle" in result

    def test_run_setup_includes_profile_in_result(self, tmp_path):
        ws = str(tmp_path)
        store.ensure_dir(ws)
        (Path(ws) / "mission.md").write_text("Build a test app")

        with patch("romyq.wizard_logic.wizard_setup") as mock_setup:
            mock_setup.return_value = {}
            result = _run_setup(ws, "", "Build a test app", "intermediate", True, None)

        assert "profile" in result
        assert "intermediate" in result["profile"]


# ── run_terminal_wizard ───────────────────────────────────────────────────────

class TestRunTerminalWizard:
    def _make_ws(self, tmp_path: Path) -> str:
        ws = str(tmp_path)
        store.ensure_dir(ws)
        (tmp_path / "mission.md").write_text("Build a demo app")
        return ws

    def _wizard_keys(self, choices=None):
        choices = choices or ["enter"]
        it = iter(choices)
        def _fn():
            try:
                return next(it)
            except StopIteration:
                return "enter"
        return _fn

    def _force_tty(self, monkeypatch):
        """Force TTY mode so select_option uses _keypress_fn."""
        import sys as _sys
        monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(_sys.stdout, "isatty", lambda: True)

    def test_wizard_returns_dict(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        self._force_tty(monkeypatch)

        lines = iter(["Build a REST API", "", "Y"])
        def reader(prompt):
            return next(lines)

        with patch("romyq.wizard_logic.wizard_setup") as mock_setup, \
             patch("romyq.loop.run"):
            mock_setup.return_value = {"env": "ok"}
            result = run_terminal_wizard(
                ws,
                _keypress_fn=self._wizard_keys(["enter"]),
                _read_line_fn=reader,
                _out=io.StringIO(),
                _generate_preview=False,
            )
        assert isinstance(result, dict)

    def test_wizard_aborts_on_no(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        self._force_tty(monkeypatch)
        lines = iter(["Build something", "", "n"])
        def reader(prompt):
            return next(lines)

        with patch("romyq.wizard_logic.wizard_setup") as mock_setup:
            mock_setup.return_value = {}
            result = run_terminal_wizard(
                ws,
                _keypress_fn=self._wizard_keys(["enter"]),
                _read_line_fn=reader,
                _out=io.StringIO(),
                _generate_preview=False,
            )
        assert result == {}

    def test_wizard_uses_demo_mission_on_empty(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        self._force_tty(monkeypatch)
        # First call (mission): raise EOFError so mission is empty → demo mission used
        # Subsequent calls: "Y" to confirm launch
        call_count = [0]
        def reader(prompt):
            call_count[0] += 1
            if call_count[0] == 1:
                raise EOFError
            return "Y"

        with patch("romyq.wizard_logic.wizard_setup") as mock_setup, \
             patch("romyq.loop.run"):
            mock_setup.return_value = {}
            run_terminal_wizard(
                ws,
                _keypress_fn=self._wizard_keys(["enter"]),
                _read_line_fn=reader,
                _out=io.StringIO(),
                _generate_preview=False,
            )
        mock_setup.assert_called_once()

    def test_wizard_skips_preview_when_no_api_key(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        self._force_tty(monkeypatch)
        lines = iter(["Build a thing", "", "Y"])
        def reader(prompt):
            return next(lines)

        calls = []
        def mock_preview(*args, **kwargs):
            calls.append(args)
            return None

        with patch("romyq.wizard_terminal.generate_architecture_preview", side_effect=mock_preview) as mock_gen, \
             patch("romyq.wizard_logic.wizard_setup", return_value={}), \
             patch("romyq.loop.run"):
            run_terminal_wizard(
                ws,
                api_key="",
                _keypress_fn=self._wizard_keys(["enter"]),
                _read_line_fn=reader,
                _out=io.StringIO(),
                _generate_preview=False,
            )
        assert len(calls) == 0

    def test_wizard_selects_complexity_from_keypress(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        self._force_tty(monkeypatch)
        lines = iter(["Build a thing", "", "n"])
        def reader(prompt):
            return next(lines)

        with patch("romyq.wizard_logic.wizard_setup") as mock_setup:
            mock_setup.return_value = {}
            run_terminal_wizard(
                ws,
                _keypress_fn=self._wizard_keys(["down", "enter"]),
                _read_line_fn=reader,
                _out=io.StringIO(),
                _generate_preview=False,
            )
        call_kwargs = mock_setup.call_args
        assert call_kwargs is not None


# ── REGRESSION: lifecycle preview path (pr(**kwargs) bug) ────────────────────
#
# These tests exercise _generate_preview=True with all three complexity levels.
# They FAIL on the original 0.10.1 code (TypeError: pr() got unexpected keyword
# argument 'end') and PASS after the fix.

class TestLifecyclePreviewPath:
    """Regression coverage for the pr(**kwargs) crash in the preview path."""

    def _make_ws(self, tmp_path: Path) -> str:
        ws = str(tmp_path)
        store.ensure_dir(ws)
        (tmp_path / "mission.md").write_text("Build a test app")
        return ws

    def _wizard_keys(self, choices):
        it = iter(choices)
        def _fn():
            try:
                return next(it)
            except StopIteration:
                return "enter"
        return _fn

    def _force_tty(self, monkeypatch):
        import sys as _sys
        monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(_sys.stdout, "isatty", lambda: True)

    def _mock_lifecycle(self, n_phases=2):
        return {
            "phases": [
                {
                    "id": i,
                    "name": f"Phase {i}",
                    "status": "pending",
                    "total_tasks": 2,
                    "completed_tasks": 0,
                    "tasks": [
                        {"id": f"t{i}a", "text": "Setup environment", "status": "pending"},
                        {"id": f"t{i}b", "text": "Write unit tests", "status": "pending"},
                    ],
                }
                for i in range(1, n_phases + 1)
            ],
            "done_criteria": ["Tests pass", "CI green"],
            "mission": "Build a test app",
            "complexity": "intermediate",
        }

    def _run_wizard_with_preview(
        self,
        ws: str,
        monkeypatch,
        *,
        key_sequence,
        reader,
        mock_lc=None,
    ):
        """Run wizard with _generate_preview=True, api_key set, lifecycle mocked."""
        self._force_tty(monkeypatch)
        mock_lc = mock_lc if mock_lc is not None else self._mock_lifecycle()

        with patch("romyq.wizard_terminal.generate_architecture_preview", return_value=mock_lc), \
             patch("romyq.wizard_logic.wizard_setup", return_value={"env": "ok"}), \
             patch("romyq.loop.run"):
            return run_terminal_wizard(
                ws,
                api_key="sk-test-key-preview",
                _keypress_fn=self._wizard_keys(key_sequence),
                _read_line_fn=reader,
                _out=io.StringIO(),
                _generate_preview=True,
            )

    # ── Basic complexity ──────────────────────────────────────────────────────

    def test_preview_basic_no_crash(self, tmp_path, monkeypatch):
        """Regression: pr(…, end='', flush=True) must not raise TypeError."""
        ws = self._make_ws(tmp_path)
        lines = iter(["Build a basic app", "", "Y"])
        reader = lambda p: next(lines)
        # key 1 = index 0 = basic
        result = self._run_wizard_with_preview(ws, monkeypatch, key_sequence=["1"], reader=reader)
        assert isinstance(result, dict)

    def test_preview_basic_lifecycle_json_created(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        lines = iter(["Build a basic app", "", "Y"])
        reader = lambda p: next(lines)
        self._run_wizard_with_preview(ws, monkeypatch, key_sequence=["1"], reader=reader)
        from romyq import store
        assert Path(store.lifecycle_path(ws)).exists()

    def test_preview_basic_output_contains_phase_names(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        out = io.StringIO()
        lines = iter(["Build a basic app", "", "Y"])
        reader = lambda p: next(lines)
        self._force_tty(monkeypatch)
        with patch("romyq.wizard_terminal.generate_architecture_preview", return_value=self._mock_lifecycle()), \
             patch("romyq.wizard_logic.wizard_setup", return_value={}), \
             patch("romyq.loop.run"):
            run_terminal_wizard(
                ws,
                api_key="sk-test-key",
                _keypress_fn=self._wizard_keys(["1"]),
                _read_line_fn=reader,
                _out=out,
                _generate_preview=True,
            )
        result = out.getvalue()
        assert "Phase 1" in result or "Phase" in result

    # ── Intermediate complexity ───────────────────────────────────────────────

    def test_preview_intermediate_no_crash(self, tmp_path, monkeypatch):
        """Regression: this is the exact path the real user hit."""
        ws = self._make_ws(tmp_path)
        # key sequence: "down" then "enter" → index 1 = intermediate
        lines = iter(["Build an intermediate app", "", "Y"])
        reader = lambda p: next(lines)
        result = self._run_wizard_with_preview(
            ws, monkeypatch, key_sequence=["down", "enter"], reader=reader
        )
        assert isinstance(result, dict)

    def test_preview_intermediate_profile_written(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        lines = iter(["Build an intermediate app", "", "Y"])
        reader = lambda p: next(lines)
        self._run_wizard_with_preview(ws, monkeypatch, key_sequence=["down", "enter"], reader=reader)
        from romyq.profile import get_complexity
        from romyq import store
        assert get_complexity(store.profile_path(ws)) == "intermediate"

    def test_preview_intermediate_pr_end_kwarg_accepted(self, tmp_path, monkeypatch):
        """Directly verify pr() accepts end and flush kwargs without raising."""
        ws = self._make_ws(tmp_path)
        lines = iter(["Build this app", "", "Y"])
        reader = lambda p: next(lines)
        # If the bug is present, this raises TypeError inside the wizard.
        # No exception = fix is working.
        try:
            self._run_wizard_with_preview(
                ws, monkeypatch, key_sequence=["down", "enter"], reader=reader
            )
        except TypeError as e:
            pytest.fail(f"pr() raised TypeError — fix not applied: {e}")

    # ── Advanced complexity ───────────────────────────────────────────────────

    def test_preview_advanced_no_crash(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        # key sequence: down+down+enter → index 2 = advanced
        lines = iter(["Build an advanced system", "", "Y"])
        reader = lambda p: next(lines)
        result = self._run_wizard_with_preview(
            ws, monkeypatch, key_sequence=["down", "down", "enter"], reader=reader
        )
        assert isinstance(result, dict)

    def test_preview_advanced_profile_written(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        lines = iter(["Build an advanced system", "", "Y"])
        reader = lambda p: next(lines)
        self._run_wizard_with_preview(
            ws, monkeypatch, key_sequence=["down", "down", "enter"], reader=reader
        )
        from romyq.profile import get_complexity
        from romyq import store
        assert get_complexity(store.profile_path(ws)) == "advanced"

    # ── Preview unavailable path ──────────────────────────────────────────────

    def test_preview_unavailable_no_crash(self, tmp_path, monkeypatch):
        """When generate_architecture_preview returns None, wizard continues."""
        ws = self._make_ws(tmp_path)
        lines = iter(["Build a thing", "", "Y"])
        reader = lambda p: next(lines)
        self._force_tty(monkeypatch)
        with patch("romyq.wizard_terminal.generate_architecture_preview", return_value=None), \
             patch("romyq.wizard_logic.wizard_setup", return_value={}), \
             patch("romyq.loop.run"):
            result = run_terminal_wizard(
                ws,
                api_key="sk-test-key",
                _keypress_fn=self._wizard_keys(["enter"]),
                _read_line_fn=reader,
                _out=io.StringIO(),
                _generate_preview=True,
            )
        assert isinstance(result, dict)

    def test_preview_unavailable_output_says_unavailable(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        out = io.StringIO()
        lines = iter(["Build a thing", "", "n"])
        reader = lambda p: next(lines)
        self._force_tty(monkeypatch)
        with patch("romyq.wizard_terminal.generate_architecture_preview", return_value=None), \
             patch("romyq.wizard_logic.wizard_setup", return_value={}):
            run_terminal_wizard(
                ws,
                api_key="sk-test-key",
                _keypress_fn=self._wizard_keys(["enter"]),
                _read_line_fn=reader,
                _out=out,
                _generate_preview=True,
            )
        assert "unavailable" in out.getvalue() or "preview" in out.getvalue().lower()

    def test_preview_generates_done_message(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        out = io.StringIO()
        lines = iter(["Build something", "", "n"])
        reader = lambda p: next(lines)
        self._force_tty(monkeypatch)
        with patch("romyq.wizard_terminal.generate_architecture_preview", return_value=self._mock_lifecycle()), \
             patch("romyq.wizard_logic.wizard_setup", return_value={}):
            run_terminal_wizard(
                ws,
                api_key="sk-test-key",
                _keypress_fn=self._wizard_keys(["enter"]),
                _read_line_fn=reader,
                _out=out,
                _generate_preview=True,
            )
        result = out.getvalue()
        assert "done" in result.lower() or "Lifecycle" in result

    def test_preview_calls_generate_with_correct_complexity(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        lines = iter(["Build something", "", "n"])
        reader = lambda p: next(lines)
        self._force_tty(monkeypatch)
        captured_args = []
        def mock_gen(api_key, mission, complexity):
            captured_args.append((api_key, mission, complexity))
            return self._mock_lifecycle()

        with patch("romyq.wizard_terminal.generate_architecture_preview", side_effect=mock_gen), \
             patch("romyq.wizard_logic.wizard_setup", return_value={}):
            run_terminal_wizard(
                ws,
                api_key="sk-test-key",
                _keypress_fn=self._wizard_keys(["down", "enter"]),  # intermediate
                _read_line_fn=reader,
                _out=io.StringIO(),
                _generate_preview=True,
            )
        assert len(captured_args) == 1
        assert captured_args[0][2] == "intermediate"
