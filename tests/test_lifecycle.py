"""Tests for romyq.lifecycle — lifecycle model, phases, tasks, progress tracking."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from romyq.lifecycle import (
    _build_lifecycle,
    _default_phases,
    _parse_lifecycle_from_text,
    _recompute_phase_progress,
    _validate_phases,
    all_phases_complete,
    current_phase,
    format_current_phase,
    format_roadmap,
    load,
    mark_task_active,
    mark_task_complete,
    next_pending_task,
    progress_summary,
    reset_active_tasks,
    save,
    skip_task,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _lc_path(tmp_path) -> str:
    return str(tmp_path / "lifecycle.json")


def _simple_lifecycle() -> dict:
    phases = _validate_phases([
        {"id": 1, "name": "Setup", "tasks": [
            {"id": "1.1", "text": "Init project structure"},
            {"id": "1.2", "text": "Set up dependencies"},
        ]},
        {"id": 2, "name": "Core", "tasks": [
            {"id": "2.1", "text": "Implement parser"},
            {"id": "2.2", "text": "Implement evaluator"},
        ]},
    ])
    return _build_lifecycle(phases, "Test mission", "intermediate", ["software runs"])


def _save_simple(tmp_path) -> tuple[str, dict]:
    p = _lc_path(tmp_path)
    data = _simple_lifecycle()
    save(p, data)
    return p, data


# ── load ──────────────────────────────────────────────────────────────────────

class TestLoad:
    def test_missing_file_returns_empty(self, tmp_path):
        p = str(tmp_path / "nonexistent.json")
        data = load(p)
        assert data["phases"] == []

    def test_corrupt_returns_empty(self, tmp_path):
        p = _lc_path(tmp_path)
        with open(p, "w") as f:
            f.write("not json!!!{")
        data = load(p)
        assert data["phases"] == []

    def test_non_dict_returns_empty(self, tmp_path):
        p = _lc_path(tmp_path)
        with open(p, "w") as f:
            json.dump([1, 2, 3], f)
        data = load(p)
        assert data["phases"] == []

    def test_sets_defaults_for_missing_keys(self, tmp_path):
        p = _lc_path(tmp_path)
        with open(p, "w") as f:
            json.dump({"phases": []}, f)
        data = load(p)
        assert "version" in data
        assert "project" in data
        assert "complexity" in data
        assert "done_criteria" in data

    def test_roundtrip(self, tmp_path):
        p, orig = _save_simple(tmp_path)
        loaded = load(p)
        assert loaded["phases"][0]["name"] == "Setup"


# ── save ──────────────────────────────────────────────────────────────────────

class TestSave:
    def test_creates_file(self, tmp_path):
        p = _lc_path(tmp_path)
        save(p, {"phases": [], "version": 1})
        assert os.path.exists(p)

    def test_writes_valid_json(self, tmp_path):
        p = _lc_path(tmp_path)
        data = {"phases": [{"id": 1}], "version": 1}
        save(p, data)
        with open(p) as f:
            loaded = json.load(f)
        assert loaded["phases"][0]["id"] == 1

    def test_atomic_write(self, tmp_path):
        p = _lc_path(tmp_path)
        save(p, {"phases": [], "done": True})
        data = load(p)
        assert data.get("done") is True


# ── _parse_lifecycle_from_text ────────────────────────────────────────────────

class TestParseLifecycleFromText:
    def test_parses_clean_json(self):
        text = json.dumps({"phases": [{"id": 1, "name": "Setup", "tasks": []}]})
        phases = _parse_lifecycle_from_text(text)
        assert phases is not None
        assert len(phases) == 1

    def test_strips_markdown_fences(self):
        text = "```json\n" + json.dumps({"phases": [{"id": 1, "name": "Setup", "tasks": []}]}) + "\n```"
        phases = _parse_lifecycle_from_text(text)
        assert phases is not None

    def test_returns_none_on_invalid(self):
        phases = _parse_lifecycle_from_text("not json at all")
        assert phases is None

    def test_extracts_phases_key(self):
        text = json.dumps({"phases": [{"id": 1, "name": "A"}, {"id": 2, "name": "B"}]})
        phases = _parse_lifecycle_from_text(text)
        assert len(phases) == 2

    def test_handles_extra_text_before_json(self):
        text = "Here is the lifecycle:\n" + json.dumps({"phases": [{"id": 1, "name": "X", "tasks": []}]})
        phases = _parse_lifecycle_from_text(text)
        assert phases is not None

    def test_empty_phases_list(self):
        text = json.dumps({"phases": []})
        phases = _parse_lifecycle_from_text(text)
        assert phases == []

    def test_returns_none_for_missing_phases_key(self):
        text = json.dumps({"steps": [1, 2, 3]})
        phases = _parse_lifecycle_from_text(text)
        assert phases is None


# ── _validate_phases ──────────────────────────────────────────────────────────

class TestValidatePhases:
    def test_basic_validation(self):
        raw = [{"id": 1, "name": "Setup", "tasks": [
            {"id": "1.1", "text": "Create project structure"}
        ]}]
        phases = _validate_phases(raw)
        assert len(phases) == 1
        assert phases[0]["name"] == "Setup"

    def test_skips_non_dict_phases(self):
        raw = ["not a dict", {"id": 1, "name": "Setup", "tasks": [{"id": "1.1", "text": "Create structure"}]}]
        phases = _validate_phases(raw)
        assert len(phases) == 1

    def test_skips_phases_with_no_valid_tasks(self):
        raw = [{"id": 1, "name": "Empty", "tasks": []}]
        phases = _validate_phases(raw)
        assert len(phases) == 0

    def test_normalizes_task_status_to_pending(self):
        raw = [{"id": 1, "name": "Phase", "tasks": [
            {"id": "1.1", "text": "Do something", "status": "complete"}
        ]}]
        phases = _validate_phases(raw)
        assert phases[0]["tasks"][0]["status"] == "pending"

    def test_sets_progress_fields(self):
        raw = [{"id": 1, "name": "Phase", "tasks": [
            {"id": "1.1", "text": "Task one"},
            {"id": "1.2", "text": "Task two"},
        ]}]
        phases = _validate_phases(raw)
        assert phases[0]["total_tasks"] == 2
        assert phases[0]["completed_tasks"] == 0
        assert phases[0]["percentage_complete"] == 0

    def test_skips_tasks_with_short_text(self):
        raw = [{"id": 1, "name": "Phase", "tasks": [
            {"id": "1.1", "text": "ok"},
            {"id": "1.2", "text": "Valid task text"},
        ]}]
        phases = _validate_phases(raw)
        assert phases[0]["total_tasks"] == 1


# ── _build_lifecycle ──────────────────────────────────────────────────────────

class TestBuildLifecycle:
    def test_marks_first_phase_active(self):
        phases = _validate_phases([{"id": 1, "name": "Phase 1", "tasks": [
            {"id": "1.1", "text": "First task"}
        ]}])
        lc = _build_lifecycle(phases, "mission", "basic", ["software runs"])
        assert lc["phases"][0]["status"] == "active"

    def test_sets_current_phase_id(self):
        phases = _validate_phases([{"id": 1, "name": "Phase 1", "tasks": [
            {"id": "1.1", "text": "First task"}
        ]}])
        lc = _build_lifecycle(phases, "mission", "basic", ["software runs"])
        assert lc["current_phase_id"] == 1

    def test_marks_first_task_active(self):
        phases = _validate_phases([{"id": 1, "name": "Phase 1", "tasks": [
            {"id": "1.1", "text": "First task"},
            {"id": "1.2", "text": "Second task"},
        ]}])
        lc = _build_lifecycle(phases, "mission", "basic", [])
        assert lc["phases"][0]["tasks"][0]["status"] == "active"

    def test_stores_done_criteria(self):
        phases = _validate_phases([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        lc = _build_lifecycle(phases, "m", "intermediate", ["software runs", "tests pass"])
        assert "software runs" in lc["done_criteria"]
        assert "tests pass" in lc["done_criteria"]

    def test_truncates_mission(self):
        long_mission = "x" * 500
        phases = _validate_phases([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        lc = _build_lifecycle(phases, long_mission, "basic", [])
        assert len(lc["project"]) <= 200

    def test_has_generated_at(self):
        phases = _validate_phases([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        lc = _build_lifecycle(phases, "m", "basic", [])
        assert lc["generated_at"] != ""


# ── current_phase ─────────────────────────────────────────────────────────────

class TestCurrentPhase:
    def test_returns_active_phase(self):
        lc = _simple_lifecycle()
        phase = current_phase(lc)
        assert phase is not None
        assert phase["name"] == "Setup"

    def test_returns_none_when_no_current(self):
        lc = {"current_phase_id": None, "phases": []}
        assert current_phase(lc) is None

    def test_returns_none_when_phase_id_missing(self):
        lc = {"current_phase_id": 99, "phases": [{"id": 1}]}
        assert current_phase(lc) is None


# ── next_pending_task ─────────────────────────────────────────────────────────

class TestNextPendingTask:
    def test_returns_first_task(self):
        lc = _simple_lifecycle()
        phase, task = next_pending_task(lc)
        assert phase is not None
        assert task is not None
        assert task["id"] == "1.1"

    def test_returns_none_none_when_no_phases(self):
        lc = {"current_phase_id": None, "phases": []}
        phase, task = next_pending_task(lc)
        assert phase is None
        assert task is None

    def test_skips_complete_tasks(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        lc = load(p)
        phase, task = next_pending_task(lc)
        assert task["id"] == "1.2"


# ── all_phases_complete ───────────────────────────────────────────────────────

class TestAllPhasesComplete:
    def test_false_when_phases_pending(self):
        lc = _simple_lifecycle()
        assert not all_phases_complete(lc)

    def test_true_when_all_complete(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        mark_task_complete(p, 2, "2.1")
        mark_task_complete(p, 2, "2.2")
        lc = load(p)
        assert all_phases_complete(lc)

    def test_false_for_empty_lifecycle(self):
        assert not all_phases_complete({"phases": []})


# ── mark_task_complete ────────────────────────────────────────────────────────

class TestMarkTaskComplete:
    def test_marks_task_complete(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        result = mark_task_complete(p, 1, "1.1")
        assert result is True
        data = load(p)
        task = next(t for t in data["phases"][0]["tasks"] if t["id"] == "1.1")
        assert task["status"] == "complete"

    def test_returns_false_for_missing_task(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        result = mark_task_complete(p, 1, "9.9")
        assert result is False

    def test_advances_to_next_task(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        data = load(p)
        task_12 = next(t for t in data["phases"][0]["tasks"] if t["id"] == "1.2")
        assert task_12["status"] == "active"

    def test_phase_advances_when_all_tasks_done(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data = load(p)
        assert data["phases"][0]["status"] == "complete"
        assert data["current_phase_id"] == 2

    def test_updates_phase_progress(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        data = load(p)
        assert data["phases"][0]["completed_tasks"] == 1

    def test_sets_completed_at_timestamp(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        data = load(p)
        task = next(t for t in data["phases"][0]["tasks"] if t["id"] == "1.1")
        assert task["completed_at"] is not None

    def test_handles_string_phase_id(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        result = mark_task_complete(p, "1", "1.1")
        assert result is True

    def test_current_phase_id_none_after_all_complete(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        mark_task_complete(p, 2, "2.1")
        mark_task_complete(p, 2, "2.2")
        data = load(p)
        assert data["current_phase_id"] is None


# ── mark_task_active ──────────────────────────────────────────────────────────

class TestMarkTaskActive:
    def test_marks_task_active(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        result = mark_task_active(p, 1, "1.2")
        assert result is True
        data = load(p)
        task = next(t for t in data["phases"][0]["tasks"] if t["id"] == "1.2")
        assert task["status"] == "active"

    def test_returns_false_for_missing(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        result = mark_task_active(p, 1, "9.9")
        assert result is False


# ── skip_task ─────────────────────────────────────────────────────────────────

class TestSkipTask:
    def test_skips_task(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        result = skip_task(p, 1, "1.1")
        assert result is True
        data = load(p)
        task = next(t for t in data["phases"][0]["tasks"] if t["id"] == "1.1")
        assert task["status"] == "skipped"

    def test_advances_to_next_pending_after_skip(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        skip_task(p, 1, "1.1")
        data = load(p)
        task_12 = next(t for t in data["phases"][0]["tasks"] if t["id"] == "1.2")
        assert task_12["status"] == "active"

    def test_returns_false_for_missing(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        result = skip_task(p, 1, "9.9")
        assert result is False


# ── reset_active_tasks ────────────────────────────────────────────────────────

class TestResetActiveTasks:
    def test_resets_active_to_pending(self, tmp_path):
        p, data = _save_simple(tmp_path)
        reset_active_tasks(p)
        data = load(p)
        for phase in data["phases"]:
            for task in phase["tasks"]:
                assert task["status"] != "active"

    def test_no_op_when_no_active(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        reset_active_tasks(p)
        data = load(p)
        task_11 = next(t for t in data["phases"][0]["tasks"] if t["id"] == "1.1")
        assert task_11["status"] == "complete"


# ── _recompute_phase_progress ─────────────────────────────────────────────────

class TestRecomputePhaseProgress:
    def test_all_complete(self):
        phase = {
            "tasks": [
                {"status": "complete"},
                {"status": "complete"},
            ]
        }
        _recompute_phase_progress(phase)
        assert phase["total_tasks"] == 2
        assert phase["completed_tasks"] == 2
        assert phase["percentage_complete"] == 100

    def test_half_complete(self):
        phase = {
            "tasks": [
                {"status": "complete"},
                {"status": "pending"},
            ]
        }
        _recompute_phase_progress(phase)
        assert phase["percentage_complete"] == 50

    def test_empty_tasks(self):
        phase = {"tasks": []}
        _recompute_phase_progress(phase)
        assert phase["percentage_complete"] == 0


# ── progress_summary ──────────────────────────────────────────────────────────

class TestProgressSummary:
    def test_fresh_lifecycle(self):
        lc = _simple_lifecycle()
        summ = progress_summary(lc)
        assert summ["total_phases"] == 2
        assert summ["complete_phases"] == 0
        assert summ["total_tasks"] == 4
        assert summ["completed_tasks"] == 0

    def test_after_completing_phase(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        lc = load(p)
        summ = progress_summary(lc)
        assert summ["complete_phases"] == 1
        assert summ["completed_tasks"] == 2

    def test_empty_lifecycle(self):
        summ = progress_summary({"phases": []})
        assert summ["total_phases"] == 0
        assert summ["overall_percentage"] == 0


# ── format_roadmap ────────────────────────────────────────────────────────────

class TestFormatRoadmap:
    def test_returns_string(self):
        lc = _simple_lifecycle()
        result = format_roadmap(lc)
        assert isinstance(result, str)

    def test_contains_phase_names(self):
        lc = _simple_lifecycle()
        result = format_roadmap(lc)
        assert "Setup" in result
        assert "Core" in result

    def test_shows_active_arrow(self):
        lc = _simple_lifecycle()
        result = format_roadmap(lc)
        assert "→" in result

    def test_shows_checkmark_for_complete(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        lc = load(p)
        result = format_roadmap(lc)
        assert "✓" in result

    def test_empty_lifecycle(self):
        result = format_roadmap({"phases": []})
        assert "no lifecycle" in result.lower()


# ── format_current_phase ──────────────────────────────────────────────────────

class TestFormatCurrentPhase:
    def test_returns_string(self):
        lc = _simple_lifecycle()
        result = format_current_phase(lc)
        assert isinstance(result, str)

    def test_contains_phase_name(self):
        lc = _simple_lifecycle()
        result = format_current_phase(lc)
        assert "Setup" in result

    def test_contains_task_text(self):
        lc = _simple_lifecycle()
        result = format_current_phase(lc)
        assert "Init project structure" in result

    def test_all_complete_message(self, tmp_path):
        p, _ = _save_simple(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        mark_task_complete(p, 2, "2.1")
        mark_task_complete(p, 2, "2.2")
        lc = load(p)
        result = format_current_phase(lc)
        assert "complete" in result.lower()


# ── _default_phases ───────────────────────────────────────────────────────────

class TestDefaultPhases:
    def test_basic_has_two_phases(self):
        phases = _default_phases("basic")
        assert len(phases) == 2

    def test_intermediate_has_three_phases(self):
        phases = _default_phases("intermediate")
        assert len(phases) == 3

    def test_advanced_has_five_phases(self):
        phases = _default_phases("advanced")
        assert len(phases) == 5

    def test_all_phases_have_tasks(self):
        for level in ("basic", "intermediate", "advanced"):
            phases = _default_phases(level)
            for phase in phases:
                assert len(phase["tasks"]) > 0
