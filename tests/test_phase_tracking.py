"""Tests for lifecycle phase progress tracking and state transitions."""
from __future__ import annotations

import json
import os

import pytest

from romyq.lifecycle import (
    _build_lifecycle,
    _validate_phases,
    all_phases_complete,
    current_phase,
    load,
    mark_task_complete,
    next_pending_task,
    progress_summary,
    save,
    skip_task,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _lc_path(tmp_path) -> str:
    return str(tmp_path / "lifecycle.json")


def _three_phase_lifecycle() -> dict:
    """Three-phase lifecycle with 2 tasks each."""
    phases = _validate_phases([
        {"id": 1, "name": "Setup", "tasks": [
            {"id": "1.1", "text": "Initialize project"},
            {"id": "1.2", "text": "Configure environment"},
        ]},
        {"id": 2, "name": "Core", "tasks": [
            {"id": "2.1", "text": "Implement main logic"},
            {"id": "2.2", "text": "Add error handling"},
        ]},
        {"id": 3, "name": "Testing", "tasks": [
            {"id": "3.1", "text": "Write unit tests"},
            {"id": "3.2", "text": "Write integration tests"},
        ]},
    ])
    return _build_lifecycle(phases, "Test project", "intermediate",
                            ["software runs", "tests pass"])


def _save_three(tmp_path) -> str:
    p = _lc_path(tmp_path)
    save(p, _three_phase_lifecycle())
    return p


# ── initial state ─────────────────────────────────────────────────────────────

class TestInitialState:
    def test_first_phase_is_active(self, tmp_path):
        p = _save_three(tmp_path)
        data = load(p)
        assert data["phases"][0]["status"] == "active"

    def test_second_phase_is_pending(self, tmp_path):
        p = _save_three(tmp_path)
        data = load(p)
        assert data["phases"][1]["status"] == "pending"

    def test_current_phase_id_is_first(self, tmp_path):
        p = _save_three(tmp_path)
        data = load(p)
        assert data["current_phase_id"] == 1

    def test_first_task_is_active(self, tmp_path):
        p = _save_three(tmp_path)
        data = load(p)
        assert data["phases"][0]["tasks"][0]["status"] == "active"

    def test_second_task_is_pending(self, tmp_path):
        p = _save_three(tmp_path)
        data = load(p)
        assert data["phases"][0]["tasks"][1]["status"] == "pending"

    def test_no_phase_is_complete(self, tmp_path):
        p = _save_three(tmp_path)
        data = load(p)
        assert not all_phases_complete(data)

    def test_progress_starts_at_zero(self, tmp_path):
        p = _save_three(tmp_path)
        data = load(p)
        summ = progress_summary(data)
        assert summ["completed_tasks"] == 0
        assert summ["overall_percentage"] == 0


# ── single task completion ────────────────────────────────────────────────────

class TestSingleTaskCompletion:
    def test_task_1_1_completes(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        data = load(p)
        t = next(t for t in data["phases"][0]["tasks"] if t["id"] == "1.1")
        assert t["status"] == "complete"

    def test_task_1_2_becomes_active_after_1_1(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        data = load(p)
        t = next(t for t in data["phases"][0]["tasks"] if t["id"] == "1.2")
        assert t["status"] == "active"

    def test_phase_1_still_active_after_1_1(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        data = load(p)
        assert data["phases"][0]["status"] == "active"

    def test_phase_1_progress_50_after_1_1(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        data = load(p)
        assert data["phases"][0]["percentage_complete"] == 50
        assert data["phases"][0]["completed_tasks"] == 1


# ── phase completion and advancement ─────────────────────────────────────────

class TestPhaseAdvancement:
    def test_phase_1_complete_after_both_tasks(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data = load(p)
        assert data["phases"][0]["status"] == "complete"

    def test_phase_2_becomes_active_after_phase_1_done(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data = load(p)
        assert data["phases"][1]["status"] == "active"

    def test_current_phase_id_advances(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data = load(p)
        assert data["current_phase_id"] == 2

    def test_phase_2_first_task_becomes_active(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data = load(p)
        assert data["phases"][1]["tasks"][0]["status"] == "active"

    def test_phase_3_still_pending_after_phase_1_done(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data = load(p)
        assert data["phases"][2]["status"] == "pending"


# ── full lifecycle completion ─────────────────────────────────────────────────

class TestFullCompletion:
    def _complete_all(self, p: str) -> None:
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        mark_task_complete(p, 2, "2.1")
        mark_task_complete(p, 2, "2.2")
        mark_task_complete(p, 3, "3.1")
        mark_task_complete(p, 3, "3.2")

    def test_all_phases_complete(self, tmp_path):
        p = _save_three(tmp_path)
        self._complete_all(p)
        data = load(p)
        assert all_phases_complete(data)

    def test_current_phase_none_when_all_done(self, tmp_path):
        p = _save_three(tmp_path)
        self._complete_all(p)
        data = load(p)
        assert data["current_phase_id"] is None

    def test_next_pending_returns_none_when_done(self, tmp_path):
        p = _save_three(tmp_path)
        self._complete_all(p)
        data = load(p)
        ph, task = next_pending_task(data)
        assert ph is None
        assert task is None

    def test_progress_100_when_all_done(self, tmp_path):
        p = _save_three(tmp_path)
        self._complete_all(p)
        data = load(p)
        summ = progress_summary(data)
        assert summ["overall_percentage"] == 100
        assert summ["completed_tasks"] == 6
        assert summ["complete_phases"] == 3

    def test_all_tasks_have_completed_at(self, tmp_path):
        p = _save_three(tmp_path)
        self._complete_all(p)
        data = load(p)
        for phase in data["phases"]:
            for task in phase["tasks"]:
                assert task["completed_at"] is not None


# ── skip interactions ─────────────────────────────────────────────────────────

class TestSkipInteraction:
    def test_skipping_all_tasks_completes_phase(self, tmp_path):
        p = _save_three(tmp_path)
        skip_task(p, 1, "1.1")
        skip_task(p, 1, "1.2")
        data = load(p)
        assert data["phases"][0]["status"] == "complete"

    def test_phase_advances_after_all_skipped(self, tmp_path):
        p = _save_three(tmp_path)
        skip_task(p, 1, "1.1")
        skip_task(p, 1, "1.2")
        data = load(p)
        assert data["current_phase_id"] == 2

    def test_skip_then_complete_advances(self, tmp_path):
        p = _save_three(tmp_path)
        skip_task(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data = load(p)
        assert data["phases"][0]["status"] == "complete"


# ── progress summary math ─────────────────────────────────────────────────────

class TestProgressMath:
    def test_remaining_tasks(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        data = load(p)
        summ = progress_summary(data)
        assert summ["remaining_tasks"] == 5

    def test_partial_completion_percentage(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        mark_task_complete(p, 2, "2.1")
        data = load(p)
        summ = progress_summary(data)
        assert summ["completed_tasks"] == 3
        assert summ["total_tasks"] == 6
        assert summ["overall_percentage"] == 50

    def test_complete_phases_count(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data = load(p)
        summ = progress_summary(data)
        assert summ["complete_phases"] == 1
        assert summ["total_phases"] == 3


# ── current_phase helper ──────────────────────────────────────────────────────

class TestCurrentPhaseHelper:
    def test_returns_correct_phase(self, tmp_path):
        p = _save_three(tmp_path)
        data = load(p)
        ph = current_phase(data)
        assert ph["id"] == 1

    def test_updates_after_advance(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data = load(p)
        ph = current_phase(data)
        assert ph["id"] == 2

    def test_none_when_all_complete(self, tmp_path):
        p = _save_three(tmp_path)
        for task_id in ("1.1", "1.2"):
            mark_task_complete(p, 1, task_id)
        for task_id in ("2.1", "2.2"):
            mark_task_complete(p, 2, task_id)
        for task_id in ("3.1", "3.2"):
            mark_task_complete(p, 3, task_id)
        data = load(p)
        assert current_phase(data) is None


# ── persistence sanity ────────────────────────────────────────────────────────

class TestPersistence:
    def test_state_survives_load_reload(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        mark_task_complete(p, 1, "1.2")
        data_fresh = load(p)
        assert data_fresh["current_phase_id"] == 2
        assert data_fresh["phases"][0]["status"] == "complete"

    def test_file_is_valid_json(self, tmp_path):
        p = _save_three(tmp_path)
        mark_task_complete(p, 1, "1.1")
        with open(p) as f:
            data = json.load(f)
        assert "phases" in data
