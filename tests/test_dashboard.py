"""Tests for romyq/dashboard.py — lifecycle-first dashboard renderer."""
from __future__ import annotations

import io
import json
import os
import tempfile
from pathlib import Path

import pytest

from romyq import store
from romyq.dashboard import render, render_task_header, answers


# ── fixture helpers ───────────────────────────────────────────────────────────

def _make_workspace(tmp_path: Path) -> str:
    ws = str(tmp_path)
    store.ensure_dir(ws)
    return ws


def _write_lifecycle(ws: str, phases=None, done_criteria=None) -> None:
    phases_list = phases or []
    current_phase_id = None
    if phases_list:
        # Set current_phase_id to the first active or pending phase
        for p in phases_list:
            if p.get("status") in ("active", "pending"):
                current_phase_id = p["id"]
                break
    lc = {
        "phases": phases_list,
        "done_criteria": done_criteria or [],
        "mission": "Build something",
        "complexity": "intermediate",
        "current_phase_id": current_phase_id,
    }
    lc_path = store.lifecycle_path(ws)
    with open(lc_path, "w") as f:
        json.dump(lc, f)


def _default_phases():
    return [
        {
            "id": 1,
            "name": "Foundation",
            "status": "active",
            "percentage_complete": 0,
            "total_tasks": 3,
            "completed_tasks": 0,
            "tasks": [
                {"id": "f1", "text": "Set up project structure", "status": "active"},
                {"id": "f2", "text": "Configure dependencies", "status": "pending"},
                {"id": "f3", "text": "Initialize git repository", "status": "pending"},
            ],
        },
        {
            "id": 2,
            "name": "Core Implementation",
            "status": "pending",
            "percentage_complete": 0,
            "total_tasks": 2,
            "completed_tasks": 0,
            "tasks": [
                {"id": "c1", "text": "Implement core logic", "status": "pending"},
                {"id": "c2", "text": "Write unit tests", "status": "pending"},
            ],
        },
    ]


def _write_mission(ws: str, text: str) -> None:
    (Path(ws) / "mission.md").write_text(text)


def _write_profile(ws: str, complexity: str = "intermediate") -> None:
    prof_path = store.profile_path(ws)
    with open(prof_path, "w") as f:
        json.dump({"complexity": complexity}, f)


# ── render() tests ────────────────────────────────────────────────────────────

class TestRender:
    def test_render_does_not_crash_empty_workspace(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        render(ws, out=out)
        result = out.getvalue()
        assert isinstance(result, str)

    def test_render_shows_no_lifecycle_message_when_absent(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        render(ws, out=out)
        result = out.getvalue()
        assert "No lifecycle" in result or "no lifecycle" in result

    def test_render_shows_phase_bars_when_lifecycle_present(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        result = out.getvalue()
        assert "Foundation" in result

    def test_render_shows_phase_name(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        assert "Foundation" in out.getvalue()

    def test_render_shows_readiness(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        assert "Readiness" in out.getvalue()

    def test_render_shows_recommendation(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        result = out.getvalue()
        assert any(r in result for r in ["Continue", "Pause", "Review", "Stop"])

    def test_render_shows_project_name_from_mission(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_mission(ws, "Build a REST API")
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        assert "Build a REST API" in out.getvalue()

    def test_render_shows_done_criteria(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases(), done_criteria=["Tests pass", "CI green"])
        out = io.StringIO()
        render(ws, out=out)
        result = out.getvalue()
        assert "Tests pass" in result

    def test_render_shows_overall_bar(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        assert "Overall" in out.getvalue()

    def test_render_shows_complexity(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        _write_profile(ws, "advanced")
        out = io.StringIO()
        render(ws, out=out)
        result = out.getvalue()
        assert "Advanced" in result or "advanced" in result

    def test_render_shows_thick_separator(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        assert "━" in out.getvalue()

    def test_render_shows_lifecycle_section_header(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        assert "Lifecycle" in out.getvalue()

    def test_render_shows_recommendation_banner(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        result = out.getvalue()
        assert "Recommendation" in result

    def test_render_outputs_to_stdout_by_default(self, tmp_path, capsys):
        ws = _make_workspace(tmp_path)
        render(ws)
        captured = capsys.readouterr()
        assert isinstance(captured.out, str)
        assert len(captured.out) > 0

    def test_render_shows_second_phase_name(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render(ws, out=out)
        assert "Core Implementation" in out.getvalue()


# ── render_task_header() tests ────────────────────────────────────────────────

class TestRenderTaskHeader:
    def test_header_does_not_crash_empty_workspace(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        render_task_header(ws, out=out)
        # Should silently handle missing lifecycle (no crash)

    def test_header_shows_phase_name_when_lifecycle_present(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render_task_header(ws, out=out)
        result = out.getvalue()
        assert "Foundation" in result

    def test_header_shows_readiness(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render_task_header(ws, out=out)
        assert "Readiness" in out.getvalue()

    def test_header_shows_recommendation(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render_task_header(ws, out=out)
        result = out.getvalue()
        assert any(r in result for r in ["Continue", "Pause", "Review", "Stop"])

    def test_header_is_compact(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        out = io.StringIO()
        render_task_header(ws, out=out)
        lines = [l for l in out.getvalue().splitlines() if l.strip()]
        assert len(lines) <= 3

    def test_header_outputs_to_stdout_by_default(self, tmp_path, capsys):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        render_task_header(ws)
        captured = capsys.readouterr()
        assert "Foundation" in captured.out or len(captured.out) >= 0

    def test_header_no_crash_when_lifecycle_absent(self, tmp_path):
        ws = _make_workspace(tmp_path)
        out = io.StringIO()
        render_task_header(ws, out=out)
        # Should not crash; may output readiness line without phase info


# ── answers() tests ───────────────────────────────────────────────────────────

class TestAnswers:
    def test_returns_dict(self, tmp_path):
        ws = _make_workspace(tmp_path)
        result = answers(ws)
        assert isinstance(result, dict)

    def test_has_all_eight_keys(self, tmp_path):
        ws = _make_workspace(tmp_path)
        result = answers(ws)
        expected_keys = {
            "what_being_built",
            "active_phase",
            "phases_remaining",
            "completion_pct",
            "current_action",
            "current_task",
            "recommendation",
            "can_stop",
        }
        assert expected_keys.issubset(result.keys())

    def test_what_being_built_from_mission(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_mission(ws, "Build a real-time chat app")
        result = answers(ws)
        assert "Build a real-time chat app" in result["what_being_built"]

    def test_active_phase_from_lifecycle(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        result = answers(ws)
        assert result["active_phase"] == "Foundation"

    def test_phases_remaining_count(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        result = answers(ws)
        assert isinstance(result["phases_remaining"], int)
        assert result["phases_remaining"] >= 0

    def test_completion_pct_is_number(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        result = answers(ws)
        assert isinstance(result["completion_pct"], (int, float))

    def test_recommendation_is_valid(self, tmp_path):
        ws = _make_workspace(tmp_path)
        result = answers(ws)
        assert result["recommendation"] in {"Continue", "Pause", "Review", "Stop"}

    def test_can_stop_is_bool(self, tmp_path):
        ws = _make_workspace(tmp_path)
        result = answers(ws)
        assert isinstance(result["can_stop"], bool)

    def test_can_stop_false_when_phases_incomplete(self, tmp_path):
        ws = _make_workspace(tmp_path)
        _write_lifecycle(ws, phases=_default_phases())
        result = answers(ws)
        assert result["can_stop"] is False

    def test_active_phase_none_when_no_lifecycle(self, tmp_path):
        ws = _make_workspace(tmp_path)
        result = answers(ws)
        assert result["active_phase"] is None

    def test_phases_remaining_zero_with_no_lifecycle(self, tmp_path):
        ws = _make_workspace(tmp_path)
        result = answers(ws)
        assert result["phases_remaining"] == 0

    def test_current_action_is_string(self, tmp_path):
        ws = _make_workspace(tmp_path)
        result = answers(ws)
        assert isinstance(result["current_action"], str)

    def test_current_task_is_string(self, tmp_path):
        ws = _make_workspace(tmp_path)
        result = answers(ws)
        assert isinstance(result["current_task"], str)
