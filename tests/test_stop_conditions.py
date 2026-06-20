"""Tests for romyq.stop_conditions — "Good Enough" evaluation."""
from __future__ import annotations

import pytest

from romyq import stop_conditions as sc_mod


def _readiness(overall: float = 0, cats: dict | None = None) -> dict:
    """Build a readiness dict for testing."""
    categories = cats or {
        "Core Functionality": {"score": overall, "required": [], "statuses": {}},
        "Testing": {"score": overall, "required": [], "statuses": {}},
        "Security": {"score": overall, "required": [], "statuses": {}},
        "Operations": {"score": overall, "required": [], "statuses": {}},
    }
    return {"overall": overall, "label": "Test", "categories": categories}


def _state(**kwargs) -> dict:
    base = {"status": "running", "tasks_completed": 0, "consecutive_failures": 0}
    base.update(kwargs)
    return base


# ── TestEvaluate ──────────────────────────────────────────────────────────────

class TestEvaluate:
    def test_returns_dict(self):
        result = sc_mod.evaluate(_readiness(), _state())
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = sc_mod.evaluate(_readiness(), _state())
        assert "recommendation" in result
        assert "should_stop" in result
        assert "reasons" in result
        assert "overall_readiness" in result
        assert "threshold" in result
        assert "conditions" in result

    def test_continue_when_below_threshold(self):
        result = sc_mod.evaluate(_readiness(overall=50), _state())
        assert result["recommendation"] == "Continue"

    def test_stop_when_above_threshold(self):
        result = sc_mod.evaluate(_readiness(overall=85), _state())
        assert result["recommendation"] == "Stop"

    def test_stop_at_exact_threshold(self):
        result = sc_mod.evaluate(_readiness(overall=80), _state())
        assert result["recommendation"] == "Stop"

    def test_continue_just_below_threshold(self):
        result = sc_mod.evaluate(_readiness(overall=79), _state())
        assert result["recommendation"] == "Continue"

    def test_stop_when_mission_complete(self):
        result = sc_mod.evaluate(_readiness(overall=0), _state(status="completed"))
        assert result["recommendation"] == "Stop"

    def test_continue_when_mission_not_complete(self):
        result = sc_mod.evaluate(_readiness(overall=0), _state(status="running"))
        assert result["recommendation"] == "Continue"

    def test_stop_when_core_complete(self):
        cats = {
            "Core Functionality": {"score": 100.0, "required": [], "statuses": {}},
            "Testing": {"score": 0, "required": [], "statuses": {}},
            "Security": {"score": 0, "required": [], "statuses": {}},
            "Operations": {"score": 0, "required": [], "statuses": {}},
        }
        result = sc_mod.evaluate(_readiness(overall=40, cats=cats), _state())
        assert result["recommendation"] == "Stop"

    def test_custom_threshold(self):
        result = sc_mod.evaluate(_readiness(overall=60), _state(), threshold=50)
        assert result["recommendation"] == "Stop"

    def test_custom_threshold_below(self):
        result = sc_mod.evaluate(_readiness(overall=40), _state(), threshold=50)
        assert result["recommendation"] == "Continue"

    def test_should_stop_bool(self):
        r_stop = sc_mod.evaluate(_readiness(overall=90), _state())
        assert r_stop["should_stop"] is True
        r_cont = sc_mod.evaluate(_readiness(overall=10), _state())
        assert r_cont["should_stop"] is False

    def test_overall_readiness_in_result(self):
        result = sc_mod.evaluate(_readiness(overall=65), _state())
        assert result["overall_readiness"] == 65

    def test_threshold_in_result(self):
        result = sc_mod.evaluate(_readiness(), _state(), threshold=75)
        assert result["threshold"] == 75

    def test_conditions_are_bool(self):
        result = sc_mod.evaluate(_readiness(), _state())
        for name, val in result["conditions"].items():
            assert isinstance(val, bool)

    def test_three_conditions(self):
        result = sc_mod.evaluate(_readiness(), _state())
        assert len(result["conditions"]) == 3

    def test_reasons_is_list(self):
        result = sc_mod.evaluate(_readiness(), _state())
        assert isinstance(result["reasons"], list)

    def test_stop_reasons_are_met_conditions(self):
        result = sc_mod.evaluate(_readiness(overall=90), _state())
        assert result["recommendation"] == "Stop"
        for reason in result["reasons"]:
            assert result["conditions"][reason] is True

    def test_continue_reasons_are_unmet_conditions(self):
        result = sc_mod.evaluate(_readiness(overall=10), _state())
        assert result["recommendation"] == "Continue"
        for reason in result["reasons"]:
            assert result["conditions"][reason] is False

    def test_empty_readiness_is_continue(self):
        result = sc_mod.evaluate({}, {})
        assert result["recommendation"] == "Continue"

    def test_default_threshold_is_80(self):
        assert sc_mod.DEFAULT_THRESHOLD == 80


# ── TestFormatStopConditions ───────────────────────────────────────────────────

class TestFormatStopConditions:
    def test_returns_string(self):
        result = sc_mod.evaluate(_readiness(), _state())
        formatted = sc_mod.format_stop_conditions(result)
        assert isinstance(formatted, str)

    def test_contains_recommendation(self):
        result = sc_mod.evaluate(_readiness(overall=90), _state())
        formatted = sc_mod.format_stop_conditions(result)
        assert "Stop" in formatted

    def test_contains_continue_recommendation(self):
        result = sc_mod.evaluate(_readiness(overall=10), _state())
        formatted = sc_mod.format_stop_conditions(result)
        assert "Continue" in formatted

    def test_contains_readiness_percentage(self):
        result = sc_mod.evaluate(_readiness(overall=65), _state())
        formatted = sc_mod.format_stop_conditions(result)
        assert "65" in formatted

    def test_contains_threshold(self):
        result = sc_mod.evaluate(_readiness(), _state(), threshold=80)
        formatted = sc_mod.format_stop_conditions(result)
        assert "80" in formatted

    def test_shows_condition_icons(self):
        result = sc_mod.evaluate(_readiness(overall=90), _state())
        formatted = sc_mod.format_stop_conditions(result)
        assert "✓" in formatted or "✗" in formatted

    def test_shows_reasons(self):
        result = sc_mod.evaluate(_readiness(overall=90), _state())
        formatted = sc_mod.format_stop_conditions(result)
        assert "Why stop" in formatted or "readiness" in formatted.lower()


# ── TestCheckCoreComplete ──────────────────────────────────────────────────────

class TestCheckCoreComplete:
    def test_true_when_core_100(self):
        cats = {"Core Functionality": {"score": 100.0}}
        r = {"categories": cats}
        assert sc_mod._check_core_complete(r, {}, 80) is True

    def test_false_when_core_partial(self):
        cats = {"Core Functionality": {"score": 50.0}}
        r = {"categories": cats}
        assert sc_mod._check_core_complete(r, {}, 80) is False

    def test_false_when_core_absent(self):
        r = {"categories": {}}
        assert sc_mod._check_core_complete(r, {}, 80) is False
