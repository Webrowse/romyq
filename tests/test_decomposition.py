"""Tests for romyq.decomposition — plan.json CRUD and task parsing."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq import decomposition as dec_mod


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def plan_file(tmp_path):
    return str(tmp_path / "plan.json")


def _write_plan(plan_path: str, tasks: list[dict]) -> str:
    data = {
        "version": 1,
        "generated_at": "2025-01-01T00:00:00+00:00",
        "mission": "test mission",
        "tasks": tasks,
    }
    Path(plan_path).write_text(json.dumps(data), encoding="utf-8")
    return plan_path


def _pending(text: str) -> dict:
    return {"text": text, "status": "pending"}


def _task(text: str, status: str = "pending") -> dict:
    return {"text": text, "status": status}


# ── TestLoadPlan ──────────────────────────────────────────────────────────────

class TestLoadPlan:
    def test_returns_empty_on_missing_file(self, plan_file):
        data = dec_mod.load_plan(plan_file)
        assert data["tasks"] == []
        assert data["mission"] == ""

    def test_returns_empty_on_corrupt_json(self, plan_file):
        Path(plan_file).write_text("not json", encoding="utf-8")
        data = dec_mod.load_plan(plan_file)
        assert data["tasks"] == []

    def test_loads_existing_plan(self, plan_file):
        _write_plan(plan_file, [_pending("implement login")])
        data = dec_mod.load_plan(plan_file)
        assert len(data["tasks"]) == 1
        assert data["tasks"][0]["text"] == "implement login"

    def test_sets_defaults_for_missing_keys(self, plan_file):
        Path(plan_file).write_text(json.dumps({"tasks": []}), encoding="utf-8")
        data = dec_mod.load_plan(plan_file)
        assert "version" in data
        assert "mission" in data
        assert "generated_at" in data

    def test_returns_empty_on_non_dict(self, plan_file):
        Path(plan_file).write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        data = dec_mod.load_plan(plan_file)
        assert data["tasks"] == []


# ── TestWritePlan ─────────────────────────────────────────────────────────────

class TestWritePlan:
    def test_writes_and_returns_path(self, plan_file):
        data = {"version": 1, "generated_at": "", "mission": "", "tasks": []}
        result = dec_mod.write_plan(plan_file, data)
        assert result == plan_file
        assert Path(plan_file).exists()

    def test_written_file_is_valid_json(self, plan_file):
        data = {"version": 1, "tasks": [_pending("test task")]}
        dec_mod.write_plan(plan_file, data)
        loaded = json.loads(Path(plan_file).read_text())
        assert loaded["tasks"][0]["text"] == "test task"

    def test_overwrites_existing(self, plan_file):
        _write_plan(plan_file, [_pending("old task")])
        new_data = {"version": 1, "tasks": [_pending("new task")]}
        dec_mod.write_plan(plan_file, new_data)
        loaded = dec_mod.load_plan(plan_file)
        assert loaded["tasks"][0]["text"] == "new task"


# ── TestParseTasks ────────────────────────────────────────────────────────────

class TestParseTasks:
    def test_numbered_list(self):
        text = "1. Implement login\n2. Add tests\n3. Deploy"
        tasks = dec_mod._parse_tasks(text)
        assert len(tasks) == 3
        assert tasks[0]["text"] == "Implement login"
        assert tasks[1]["text"] == "Add tests"

    def test_all_tasks_start_as_pending(self):
        text = "1. Do something\n2. Do something else"
        tasks = dec_mod._parse_tasks(text)
        for t in tasks:
            assert t["status"] == "pending"

    def test_bullet_list(self):
        text = "- Implement login\n- Add tests"
        tasks = dec_mod._parse_tasks(text)
        assert len(tasks) == 2

    def test_star_bullets(self):
        text = "* First task\n* Second task"
        tasks = dec_mod._parse_tasks(text)
        assert len(tasks) == 2

    def test_ignores_short_lines(self):
        text = "1. Hi\n2. Implement proper authentication with JWT"
        tasks = dec_mod._parse_tasks(text)
        assert len(tasks) == 1
        assert "authentication" in tasks[0]["text"]

    def test_empty_text_returns_empty(self):
        assert dec_mod._parse_tasks("") == []

    def test_non_list_text_returns_empty(self):
        text = "This is a regular paragraph with no list items."
        tasks = dec_mod._parse_tasks(text)
        assert tasks == []

    def test_numbered_with_parenthesis(self):
        text = "1) First task here\n2) Second task here"
        tasks = dec_mod._parse_tasks(text)
        assert len(tasks) == 2


# ── TestMarkStatus ────────────────────────────────────────────────────────────

class TestMarkActive:
    def test_marks_pending_as_active(self, plan_file):
        _write_plan(plan_file, [_pending("implement user login")])
        result = dec_mod.mark_active(plan_file, "implement user login")
        assert result is True
        data = dec_mod.load_plan(plan_file)
        assert data["tasks"][0]["status"] == "active"

    def test_returns_false_for_nonexistent_task(self, plan_file):
        _write_plan(plan_file, [_pending("implement login")])
        result = dec_mod.mark_active(plan_file, "nonexistent task")
        assert result is False

    def test_case_insensitive_match(self, plan_file):
        _write_plan(plan_file, [_pending("Implement User Login")])
        result = dec_mod.mark_active(plan_file, "implement user login")
        assert result is True


class TestMarkCompleted:
    def test_marks_task_completed(self, plan_file):
        _write_plan(plan_file, [_task("implement login", "active")])
        dec_mod.mark_completed(plan_file, "implement login")
        data = dec_mod.load_plan(plan_file)
        assert data["tasks"][0]["status"] == "completed"

    def test_returns_false_for_missing(self, plan_file):
        _write_plan(plan_file, [_pending("something")])
        assert dec_mod.mark_completed(plan_file, "nothing") is False


class TestMarkSkipped:
    def test_marks_task_skipped(self, plan_file):
        _write_plan(plan_file, [_pending("write docs")])
        dec_mod.mark_skipped(plan_file, "write docs")
        data = dec_mod.load_plan(plan_file)
        assert data["tasks"][0]["status"] == "skipped"


# ── TestResetActiveTasks ──────────────────────────────────────────────────────

class TestResetActiveTasks:
    def test_resets_active_to_pending(self, plan_file):
        _write_plan(plan_file, [
            _task("task 1", "active"),
            _task("task 2", "completed"),
        ])
        dec_mod.reset_active_tasks(plan_file)
        data = dec_mod.load_plan(plan_file)
        assert data["tasks"][0]["status"] == "pending"
        assert data["tasks"][1]["status"] == "completed"

    def test_no_op_when_no_active(self, plan_file):
        _write_plan(plan_file, [_pending("task 1"), _task("task 2", "completed")])
        dec_mod.reset_active_tasks(plan_file)
        data = dec_mod.load_plan(plan_file)
        assert data["tasks"][0]["status"] == "pending"
        assert data["tasks"][1]["status"] == "completed"


# ── TestPlanSummary ───────────────────────────────────────────────────────────

class TestPlanSummary:
    def test_empty_plan(self, plan_file):
        summary = dec_mod.plan_summary(plan_file)
        assert summary["total"] == 0
        assert summary["pending"] == 0

    def test_counts_all_statuses(self, plan_file):
        _write_plan(plan_file, [
            _task("t1", "pending"),
            _task("t2", "active"),
            _task("t3", "completed"),
            _task("t4", "skipped"),
            _task("t5", "pending"),
        ])
        s = dec_mod.plan_summary(plan_file)
        assert s["total"] == 5
        assert s["pending"] == 2
        assert s["active"] == 1
        assert s["completed"] == 1
        assert s["skipped"] == 1

    def test_missing_file_returns_zeros(self, plan_file):
        s = dec_mod.plan_summary(plan_file)
        assert s["total"] == 0


# ── TestFormatPlan ────────────────────────────────────────────────────────────

class TestFormatPlan:
    def test_empty_plan_message(self, plan_file):
        text = dec_mod.format_plan(plan_file)
        assert "no plan" in text.lower()

    def test_pending_icon(self, plan_file):
        _write_plan(plan_file, [_pending("implement login")])
        text = dec_mod.format_plan(plan_file)
        assert "□" in text

    def test_completed_icon(self, plan_file):
        _write_plan(plan_file, [_task("done task", "completed")])
        text = dec_mod.format_plan(plan_file)
        assert "✓" in text

    def test_active_icon(self, plan_file):
        _write_plan(plan_file, [_task("current task", "active")])
        text = dec_mod.format_plan(plan_file)
        assert "→" in text

    def test_skipped_icon(self, plan_file):
        _write_plan(plan_file, [_task("skip me", "skipped")])
        text = dec_mod.format_plan(plan_file)
        assert "–" in text

    def test_task_text_in_output(self, plan_file):
        _write_plan(plan_file, [_pending("implement user registration endpoint")])
        text = dec_mod.format_plan(plan_file)
        assert "implement user registration endpoint" in text

    def test_respects_max_tasks(self, plan_file):
        tasks = [_pending(f"task {i}") for i in range(25)]
        _write_plan(plan_file, tasks)
        text = dec_mod.format_plan(plan_file, max_tasks=5)
        assert "more tasks" in text

    def test_missing_file_returns_no_plan(self, plan_file):
        text = dec_mod.format_plan(plan_file)
        assert "no plan" in text.lower()


# ── TestConstants ─────────────────────────────────────────────────────────────

class TestConstants:
    def test_task_statuses(self):
        expected = {"pending", "active", "completed", "skipped"}
        assert dec_mod._TASK_STATUSES == expected
