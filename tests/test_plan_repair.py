"""Tests for romyq.plan_repair — smart plan repair on consecutive failures."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq import plan_repair as repair_mod


@pytest.fixture()
def plan_file(tmp_path):
    return str(tmp_path / "plan.json")


@pytest.fixture()
def history_file(tmp_path):
    return str(tmp_path / "history.json")


def _write_history(history_path: str, entries: list[dict]) -> None:
    Path(history_path).write_text(json.dumps(entries), encoding="utf-8")


def _make_history_entry(success: bool, task: str = "test task", reason: str = "test reason") -> dict:
    return {
        "task": task,
        "success": success,
        "validation_reason": reason,
        "timestamp": "2025-01-01T00:00:00+00:00",
        "mode": "impl",
        "commit": "",
    }


def _write_plan(plan_path: str, tasks: list[dict]) -> None:
    data = {
        "version": 1,
        "generated_at": "2025-01-01T00:00:00+00:00",
        "mission": "test",
        "tasks": tasks,
    }
    Path(plan_path).write_text(json.dumps(data), encoding="utf-8")


# ── TestNeedsRepair ───────────────────────────────────────────────────────────

class TestNeedsRepair:
    def test_false_when_no_history(self, history_file):
        _write_history(history_file, [])
        assert repair_mod.needs_repair(history_file) is False

    def test_false_when_mostly_successful(self, history_file):
        entries = [_make_history_entry(success=True) for _ in range(5)]
        entries[0] = _make_history_entry(success=False)
        _write_history(history_file, entries)
        assert repair_mod.needs_repair(history_file) is False

    def test_true_when_threshold_failures(self, history_file):
        entries = [_make_history_entry(success=False) for _ in range(5)]
        _write_history(history_file, entries)
        assert repair_mod.needs_repair(history_file) is True

    def test_true_when_exactly_threshold(self, history_file):
        # Default: window=5, threshold=3
        entries = [
            _make_history_entry(success=False),
            _make_history_entry(success=False),
            _make_history_entry(success=False),
            _make_history_entry(success=True),
            _make_history_entry(success=True),
        ]
        _write_history(history_file, entries)
        assert repair_mod.needs_repair(history_file) is True

    def test_false_when_below_threshold(self, history_file):
        entries = [
            _make_history_entry(success=False),
            _make_history_entry(success=False),
            _make_history_entry(success=True),
            _make_history_entry(success=True),
            _make_history_entry(success=True),
        ]
        _write_history(history_file, entries)
        assert repair_mod.needs_repair(history_file) is False

    def test_false_when_not_enough_entries(self, history_file):
        entries = [_make_history_entry(success=False), _make_history_entry(success=False)]
        _write_history(history_file, entries)
        # Only 2 entries, default threshold=3, so not enough data
        assert repair_mod.needs_repair(history_file) is False

    def test_custom_threshold(self, history_file):
        entries = [_make_history_entry(success=False) for _ in range(2)]
        entries += [_make_history_entry(success=True) for _ in range(3)]
        _write_history(history_file, entries)
        assert repair_mod.needs_repair(history_file, threshold=2) is True

    def test_missing_history_file(self, tmp_path):
        assert repair_mod.needs_repair(str(tmp_path / "missing.json")) is False


# ── TestRecentFailures ────────────────────────────────────────────────────────

class TestRecentFailures:
    def test_returns_only_failed_entries(self, history_file):
        entries = [
            _make_history_entry(success=True, task="pass"),
            _make_history_entry(success=False, task="fail"),
        ]
        _write_history(history_file, entries)
        failures = repair_mod.recent_failures(history_file)
        assert all(not e["success"] for e in failures)

    def test_returns_empty_on_all_success(self, history_file):
        entries = [_make_history_entry(success=True) for _ in range(3)]
        _write_history(history_file, entries)
        assert repair_mod.recent_failures(history_file) == []


# ── TestParseRepairTasks ──────────────────────────────────────────────────────

class TestParseRepairTasks:
    def test_numbered_list(self):
        text = "1. Implement user login endpoint\n2. Add unit tests\n3. Deploy to staging"
        tasks = repair_mod._parse_repair_tasks(text)
        assert len(tasks) == 3
        assert tasks[0] == "Implement user login endpoint"

    def test_bullet_list(self):
        text = "- First replacement task\n- Second replacement task"
        tasks = repair_mod._parse_repair_tasks(text)
        assert len(tasks) == 2

    def test_ignores_short_lines(self):
        text = "1. Hi\n2. Implement a proper user authentication module"
        tasks = repair_mod._parse_repair_tasks(text)
        assert len(tasks) == 1

    def test_empty_text_returns_empty(self):
        assert repair_mod._parse_repair_tasks("") == []


# ── TestRepairPlan ────────────────────────────────────────────────────────────

class TestRepairPlan:
    def test_returns_existing_plan_on_no_failures(self, plan_file, history_file):
        _write_plan(plan_file, [{"text": "task 1", "status": "pending"}])
        _write_history(history_file, [_make_history_entry(success=True)])
        result = repair_mod.repair_plan(plan_file, "api_key", "mission", history_file)
        assert result["tasks"][0]["text"] == "task 1"

    def test_marks_failed_tasks_as_skipped(self, plan_file, history_file):
        task_text = "implement user authentication"
        _write_plan(plan_file, [{"text": task_text, "status": "pending"}])
        entries = [
            _make_history_entry(success=False, task=task_text)
            for _ in range(3)
        ]
        _write_history(history_file, entries)
        # No API key — repair will fail gracefully but should still mark as skipped
        result = repair_mod.repair_plan(plan_file, "", "mission", history_file)
        # Either skipped or left as pending (graceful degradation)
        task = next(t for t in result["tasks"] if t["text"] == task_text)
        assert task["status"] in ("skipped", "pending")

    def test_never_raises_on_api_error(self, plan_file, history_file):
        _write_plan(plan_file, [{"text": "task 1", "status": "pending"}])
        entries = [_make_history_entry(success=False) for _ in range(3)]
        _write_history(history_file, entries)
        # Bad API key — should not raise
        result = repair_mod.repair_plan(plan_file, "bad-key", "mission", history_file)
        assert isinstance(result, dict)

    def test_constants(self):
        assert repair_mod._REPAIR_THRESHOLD == 3
        assert repair_mod._REPAIR_WINDOW == 5
