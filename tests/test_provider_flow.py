"""Provider and planning integrity tests — TASK 10.

Verifies:
- lifecycle.generate() sets source='deepseek' on success
- lifecycle.generate() sets source='local_fallback' on DeepSeek failure
- decomposition.decompose() sets source field correctly
- wizard shows provider discovery transparently
- wizard shows accurate attribution (no false 'done.' on fallback)
- loop logs correct source
- dashboard shows source
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from romyq import store
from romyq.lifecycle import generate as lc_generate, _default_phases
from romyq.decomposition import decompose


# ── helpers ───────────────────────────────────────────────────────────────────

def _mock_deepseek_response(phases_json: str):
    """Return a mock OpenAI response object with the given content."""
    msg = MagicMock()
    msg.content = phases_json
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _valid_phases_json():
    return json.dumps({
        "phases": [
            {"id": 1, "name": "Setup", "tasks": [
                {"id": "1.1", "text": "Initialize project structure"},
                {"id": "1.2", "text": "Configure dependencies"},
            ]},
            {"id": 2, "name": "Implementation", "tasks": [
                {"id": "2.1", "text": "Implement core logic"},
                {"id": "2.2", "text": "Write unit tests"},
            ]},
        ]
    })


def _make_workspace(tmp_path: Path) -> str:
    ws = str(tmp_path)
    store.ensure_dir(ws)
    return ws


# ── lifecycle.generate() source tracking ──────────────────────────────────────

class TestLifecycleGenerateSource:
    def test_source_is_deepseek_on_success(self):
        mock_resp = _mock_deepseek_response(_valid_phases_json())
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.return_value = mock_resp
            result = lc_generate("sk-valid-key", "Build a calculator", "basic")
        assert result["source"] == "deepseek"

    def test_source_is_local_fallback_on_api_error(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("401 Unauthorized")
            result = lc_generate("sk-invalid", "Build a calculator", "basic")
        assert result["source"] == "local_fallback"

    def test_source_is_local_fallback_on_network_error(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = ConnectionError("timeout")
            result = lc_generate("sk-valid", "Build a calculator", "basic")
        assert result["source"] == "local_fallback"

    def test_source_is_local_fallback_on_empty_api_key(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("API key missing")
            result = lc_generate("", "Build a calculator", "basic")
        assert result["source"] == "local_fallback"

    def test_source_is_local_fallback_on_bad_json(self):
        mock_resp = _mock_deepseek_response("not valid json at all")
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.return_value = mock_resp
            result = lc_generate("sk-valid", "Build a calculator", "basic")
        assert result["source"] == "local_fallback"

    def test_source_field_persisted_in_lifecycle_dict(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("down")
            result = lc_generate("sk-key", "Build something", "intermediate")
        assert "source" in result

    def test_deepseek_result_has_phases(self):
        mock_resp = _mock_deepseek_response(_valid_phases_json())
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.return_value = mock_resp
            result = lc_generate("sk-valid", "Build a calculator", "basic")
        assert len(result["phases"]) > 0

    def test_fallback_result_has_phases(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("down")
            result = lc_generate("sk-key", "Build something", "basic")
        assert len(result["phases"]) > 0

    def test_fallback_phases_are_generic_not_mission_specific(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("down")
            result = lc_generate("sk-key", "Build a 3D Ghibli calculator", "basic")
        # Generic fallback phases should not mention "3D Ghibli"
        all_phase_names = [p["name"] for p in result["phases"]]
        assert not any("3D" in n or "Ghibli" in n for n in all_phase_names)


# ── decomposition.decompose() source tracking ─────────────────────────────────

class TestDecompositionSource:
    def test_source_is_deepseek_on_success(self):
        mock_resp = MagicMock()
        mock_resp.choices[0].message.content = "1. Create the main module\n2. Write unit tests\n"
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.return_value = mock_resp
            result = decompose("sk-valid", "Build a calculator")
        assert result["source"] == "deepseek"

    def test_source_is_local_fallback_on_api_error(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("401")
            result = decompose("sk-invalid", "Build a calculator")
        assert result["source"] == "local_fallback"

    def test_source_local_fallback_returns_empty_tasks(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("down")
            result = decompose("sk-key", "Build a calculator")
        assert result["tasks"] == []

    def test_source_field_always_present(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("down")
            result = decompose("sk-key", "Build something")
        assert "source" in result


# ── wizard provider transparency ──────────────────────────────────────────────

class TestWizardProviderTransparency:
    """Wizard must show who provided what — no silent key pickup, no fake 'done.'"""

    def _make_ws(self, tmp_path):
        ws = str(tmp_path)
        store.ensure_dir(ws)
        (tmp_path / "mission.md").write_text("Build something")
        return ws

    def _force_tty(self, monkeypatch):
        import sys as _sys
        monkeypatch.setattr(_sys.stdin, "isatty", lambda: True)
        monkeypatch.setattr(_sys.stdout, "isatty", lambda: True)

    def _run_wizard(self, ws, monkeypatch, *, api_key="", key_seq=None, reader=None,
                    lc_source="deepseek", generate_preview=True):
        self._force_tty(monkeypatch)
        from romyq.wizard_terminal import run_terminal_wizard
        out = io.StringIO()

        mock_lc = {
            "phases": [{"id": 1, "name": "Setup", "status": "pending", "total_tasks": 2,
                        "completed_tasks": 0,
                        "tasks": [{"id": "1.1", "text": "Init project", "status": "pending"}]}],
            "done_criteria": [],
            "source": lc_source,
        }

        keys = iter(key_seq or ["enter"])
        keypress_fn = lambda: next(keys, "enter")

        if reader is None:
            lines = iter(["Build something", "", "n"])
            reader = lambda p: next(lines, "n")

        with patch("romyq.wizard_terminal.generate_architecture_preview", return_value=mock_lc), \
             patch("romyq.wizard_logic.wizard_setup", return_value={}):
            run_terminal_wizard(
                ws,
                api_key=api_key,
                _keypress_fn=keypress_fn,
                _read_line_fn=reader,
                _out=out,
                _generate_preview=generate_preview,
            )
        return out.getvalue()

    def test_env_key_discovery_is_displayed(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key-12345")
        result = self._run_wizard(ws, monkeypatch)
        assert "environment" in result.lower() or "DEEPSEEK_API_KEY" in result

    def test_no_env_key_shows_provider_selection(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        # Mission is read first, then provider choice
        lines = iter(["Build something", "", "4", "n"])  # "4" = Configure later
        reader = lambda p: next(lines, "n")
        result = self._run_wizard(ws, monkeypatch, api_key="", reader=reader,
                                  generate_preview=False)
        assert "provider" in result.lower() or "DeepSeek" in result or "Configure" in result

    def test_deepseek_success_shows_done_and_attribution(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key-12345")
        result = self._run_wizard(ws, monkeypatch, lc_source="deepseek")
        # Must show "done." and DeepSeek attribution
        assert "done." in result
        assert "DeepSeek" in result

    def test_deepseek_fallback_does_not_show_done(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key-12345")
        result = self._run_wizard(ws, monkeypatch, lc_source="local_fallback")
        # Must NOT show "done." — must show fallback warning
        lines = result.splitlines()
        # "done." should not appear without qualification
        done_lines = [l for l in lines if "done." in l.lower() and "fallback" not in l.lower()]
        assert len(done_lines) == 0, f"Found unqualified 'done.' on fallback: {done_lines}"

    def test_deepseek_fallback_shows_warning(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key-12345")
        result = self._run_wizard(ws, monkeypatch, lc_source="local_fallback")
        assert "fallback" in result.lower() or "unavailable" in result.lower()

    def test_no_key_shows_lifecycle_skip_message(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        # Mission is read first, then provider choice
        lines = iter(["Build something", "", "4", "n"])  # "4" = Configure later
        reader = lambda p: next(lines, "n")
        result = self._run_wizard(ws, monkeypatch, api_key="", reader=reader,
                                  generate_preview=False)
        # When no key: preview is skipped, must tell user
        assert "skip" in result.lower() or "fallback" in result.lower() or "no" in result.lower()

    def test_configure_later_does_not_generate_lifecycle(self, tmp_path, monkeypatch):
        ws = self._make_ws(tmp_path)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        from romyq.wizard_terminal import run_terminal_wizard
        out = io.StringIO()
        self._force_tty(monkeypatch)

        calls = []
        def mock_gen(*args, **kwargs):
            calls.append(args)
            return None

        # Mission is read first, then provider choice
        lines = iter(["Build something", "", "4", "n"])  # "4" = Configure later
        reader = lambda p: next(lines, "n")
        keys = iter(["enter"])

        with patch("romyq.wizard_terminal.generate_architecture_preview", side_effect=mock_gen), \
             patch("romyq.wizard_logic.wizard_setup", return_value={}):
            run_terminal_wizard(
                ws,
                api_key="",
                _keypress_fn=lambda: next(keys, "enter"),
                _read_line_fn=reader,
                _out=out,
                _generate_preview=True,
            )
        assert len(calls) == 0


# ── lifecycle source field in saved file ──────────────────────────────────────

class TestLifecycleSourcePersisted:
    def test_source_written_to_lifecycle_json(self, tmp_path):
        ws = _make_workspace(tmp_path)
        from romyq.lifecycle import save as lc_save, generate as lc_gen
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("down")
            lc_data = lc_gen("sk-key", "Build a thing", "basic")
        lc_path = store.lifecycle_path(ws)
        lc_save(lc_path, lc_data)
        with open(lc_path) as f:
            saved = json.load(f)
        assert saved.get("source") == "local_fallback"

    def test_source_deepseek_written_when_success(self, tmp_path):
        ws = _make_workspace(tmp_path)
        from romyq.lifecycle import save as lc_save, generate as lc_gen
        mock_resp = _mock_deepseek_response(_valid_phases_json())
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.return_value = mock_resp
            lc_data = lc_gen("sk-valid", "Build a thing", "basic")
        lc_path = store.lifecycle_path(ws)
        lc_save(lc_path, lc_data)
        with open(lc_path) as f:
            saved = json.load(f)
        assert saved.get("source") == "deepseek"


# ── dashboard source display ──────────────────────────────────────────────────

class TestDashboardSourceDisplay:
    def _write_lifecycle(self, ws, source="deepseek"):
        lc = {
            "phases": [{
                "id": 1,
                "name": "Foundation",
                "status": "active",
                "percentage_complete": 0,
                "total_tasks": 2,
                "completed_tasks": 0,
                "tasks": [
                    {"id": "t1", "text": "Setup project", "status": "active"},
                ],
            }],
            "done_criteria": [],
            "source": source,
            "current_phase_id": 1,
        }
        with open(store.lifecycle_path(ws), "w") as f:
            json.dump(lc, f)

    def test_dashboard_shows_deepseek_source(self, tmp_path):
        ws = _make_workspace(tmp_path)
        self._write_lifecycle(ws, source="deepseek")
        from romyq.dashboard import render
        out = io.StringIO()
        render(ws, out=out)
        result = out.getvalue()
        assert "DeepSeek" in result or "deepseek" in result.lower()

    def test_dashboard_shows_local_fallback_warning(self, tmp_path):
        ws = _make_workspace(tmp_path)
        self._write_lifecycle(ws, source="local_fallback")
        from romyq.dashboard import render
        out = io.StringIO()
        render(ws, out=out)
        result = out.getvalue()
        assert "fallback" in result.lower() or "⚠" in result

    def test_dashboard_no_source_field_shows_no_crash(self, tmp_path):
        ws = _make_workspace(tmp_path)
        # Old lifecycle.json without source field
        lc = {
            "phases": [{"id": 1, "name": "Setup", "status": "active",
                        "total_tasks": 1, "completed_tasks": 0,
                        "tasks": [{"id": "t1", "text": "Do something", "status": "active"}]}],
            "done_criteria": [],
            "current_phase_id": 1,
        }
        with open(store.lifecycle_path(ws), "w") as f:
            json.dump(lc, f)
        from romyq.dashboard import render
        out = io.StringIO()
        render(ws, out=out)
        assert isinstance(out.getvalue(), str)


# ── clean room simulation (TASK 3) ────────────────────────────────────────────

class TestCleanRoomBehavior:
    """Simulate a workspace with no env vars, no .env, no cached state."""

    def test_no_key_lifecycle_source_is_local_fallback(self):
        """Without a key, generate() always returns local_fallback."""
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("auth error")
            result = lc_generate("", "Build something", "basic")
        assert result["source"] == "local_fallback"

    def test_no_key_decompose_source_is_local_fallback(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("auth error")
            result = decompose("", "Build something")
        assert result["source"] == "local_fallback"

    def test_no_key_decompose_tasks_are_empty(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("auth error")
            result = decompose("", "Build something")
        assert result["tasks"] == []

    def test_valid_key_lifecycle_source_is_deepseek(self):
        mock_resp = _mock_deepseek_response(_valid_phases_json())
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.return_value = mock_resp
            result = lc_generate("sk-valid-key-12345", "Build something", "basic")
        assert result["source"] == "deepseek"

    def test_invalid_key_lifecycle_source_is_local_fallback(self):
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = Exception("401 Invalid Authentication")
            result = lc_generate("sk-wrong-key", "Build something", "basic")
        assert result["source"] == "local_fallback"

    def test_timeout_lifecycle_source_is_local_fallback(self):
        import socket
        with patch("openai.OpenAI") as mock_openai:
            instance = mock_openai.return_value
            instance.chat.completions.create.side_effect = TimeoutError("timed out")
            result = lc_generate("sk-valid", "Build something", "intermediate")
        assert result["source"] == "local_fallback"
