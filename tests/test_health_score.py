"""Tests for romyq.health_score — mission health score computation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq import health_score as hs_mod


@pytest.fixture()
def history_file(tmp_path):
    return str(tmp_path / "history.json")


@pytest.fixture()
def events_file(tmp_path):
    p = tmp_path / "events.log"
    p.write_text("", encoding="utf-8")
    return str(p)


def _write_history(history_path: str, entries: list[dict]) -> None:
    Path(history_path).write_text(json.dumps(entries), encoding="utf-8")


def _entry(success: bool) -> dict:
    return {
        "task": "test",
        "success": success,
        "validation_reason": "ok" if success else "fail",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "mode": "impl",
        "commit": "",
    }


def _emit_event(events_path: str, event_type: str, **kwargs) -> None:
    from romyq.events import emit
    emit(events_path, event_type, **kwargs)


# ── TestComputeHealthScore ────────────────────────────────────────────────────

class TestComputeHealthScore:
    def test_returns_dict(self, history_file):
        _write_history(history_file, [])
        result = hs_mod.compute_health_score(history_file)
        assert isinstance(result, dict)

    def test_has_required_keys(self, history_file):
        _write_history(history_file, [])
        result = hs_mod.compute_health_score(history_file)
        assert "score" in result
        assert "grade" in result
        assert "components" in result

    def test_perfect_score_on_no_history(self, history_file):
        _write_history(history_file, [])
        result = hs_mod.compute_health_score(history_file)
        assert result["score"] == 100

    def test_perfect_grade_on_no_history(self, history_file):
        _write_history(history_file, [])
        result = hs_mod.compute_health_score(history_file)
        assert result["grade"] == "A"

    def test_all_success_gives_high_score(self, history_file):
        _write_history(history_file, [_entry(True) for _ in range(10)])
        result = hs_mod.compute_health_score(history_file)
        assert result["score"] >= 90
        assert result["grade"] == "A"

    def test_all_failures_gives_low_score(self, history_file):
        _write_history(history_file, [_entry(False) for _ in range(10)])
        result = hs_mod.compute_health_score(history_file)
        assert result["score"] < 85

    def test_score_in_valid_range(self, history_file):
        _write_history(history_file, [_entry(False) for _ in range(20)])
        result = hs_mod.compute_health_score(history_file)
        assert 0 <= result["score"] <= 100

    def test_consecutive_failures_deduct_score(self, history_file):
        _write_history(history_file, [_entry(True) for _ in range(5)])
        state = {"consecutive_failures": 5}
        result = hs_mod.compute_health_score(history_file, state=state)
        assert result["components"]["consecutive_failure_penalty"] < 0

    def test_no_consecutive_failures_no_penalty(self, history_file):
        _write_history(history_file, [_entry(True) for _ in range(5)])
        state = {"consecutive_failures": 0}
        result = hs_mod.compute_health_score(history_file, state=state)
        assert result["components"]["consecutive_failure_penalty"] == 0

    def test_blocked_tasks_deduct_score(self, history_file, events_file):
        _write_history(history_file, [_entry(True) for _ in range(5)])
        _emit_event(events_file, "task_blocked", key="abc")
        _emit_event(events_file, "task_blocked", key="def")
        result = hs_mod.compute_health_score(history_file, events_path=events_file)
        assert result["components"]["blocked_task_penalty"] < 0

    def test_guardrails_triggered_deduct_score(self, history_file, events_file):
        _write_history(history_file, [_entry(True) for _ in range(5)])
        _emit_event(events_file, "guardrail_triggered", reason="test")
        result = hs_mod.compute_health_score(history_file, events_path=events_file)
        assert result["components"]["guardrail_penalty"] < 0

    def test_components_contains_success_rate(self, history_file):
        _write_history(history_file, [_entry(True) for _ in range(8)] + [_entry(False) for _ in range(2)])
        result = hs_mod.compute_health_score(history_file)
        assert "success_rate" in result["components"]
        assert result["components"]["success_rate"] == pytest.approx(0.8)

    def test_components_contains_total_tasks(self, history_file):
        _write_history(history_file, [_entry(True) for _ in range(5)])
        result = hs_mod.compute_health_score(history_file)
        assert result["components"]["total_tasks"] == 5


# ── TestGrade ─────────────────────────────────────────────────────────────────

class TestGrade:
    def test_grade_a_at_85(self, history_file):
        _write_history(history_file, [])
        assert hs_mod._grade(85) == "A"
        assert hs_mod._grade(100) == "A"

    def test_grade_b_at_70(self, history_file):
        assert hs_mod._grade(70) == "B"
        assert hs_mod._grade(84) == "B"

    def test_grade_c_at_55(self, history_file):
        assert hs_mod._grade(55) == "C"
        assert hs_mod._grade(69) == "C"

    def test_grade_d_at_40(self, history_file):
        assert hs_mod._grade(40) == "D"
        assert hs_mod._grade(54) == "D"

    def test_grade_f_below_40(self, history_file):
        assert hs_mod._grade(0) == "F"
        assert hs_mod._grade(39) == "F"


# ── TestFormatHealthScore ─────────────────────────────────────────────────────

class TestFormatHealthScore:
    def test_returns_string(self, history_file):
        _write_history(history_file, [])
        health = hs_mod.compute_health_score(history_file)
        result = hs_mod.format_health_score(health)
        assert isinstance(result, str)

    def test_contains_score(self, history_file):
        _write_history(history_file, [])
        health = hs_mod.compute_health_score(history_file)
        result = hs_mod.format_health_score(health)
        assert "100" in result

    def test_contains_grade(self, history_file):
        _write_history(history_file, [])
        health = hs_mod.compute_health_score(history_file)
        result = hs_mod.format_health_score(health)
        assert "[A]" in result

    def test_contains_success_rate(self, history_file):
        _write_history(history_file, [_entry(True) for _ in range(5)])
        health = hs_mod.compute_health_score(history_file)
        result = hs_mod.format_health_score(health)
        assert "success_rate" in result
