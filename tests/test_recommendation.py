"""Tests for romyq.recommendation — Continue/Pause/Review/Stop engine."""
from __future__ import annotations

import json
import os

import pytest

from romyq.recommendation import (
    _check_done_criteria,
    _make,
    format_recommendation,
    recommend,
)
from romyq.lifecycle import _build_lifecycle, _validate_phases


# ── helpers ───────────────────────────────────────────────────────────────────

def _lifecycle(phases_raw, done_criteria=None, complexity="intermediate"):
    phases = _validate_phases(phases_raw)
    return _build_lifecycle(phases, "test mission", complexity, done_criteria or [])


def _all_complete_lifecycle():
    """Lifecycle where all phases and tasks are marked complete."""
    lc = _lifecycle([
        {"id": 1, "name": "Setup", "tasks": [{"id": "1.1", "text": "Init project"}]},
        {"id": 2, "name": "Core", "tasks": [{"id": "2.1", "text": "Implement core"}]},
    ], done_criteria=["software runs"])
    for phase in lc["phases"]:
        phase["status"] = "complete"
        for task in phase["tasks"]:
            task["status"] = "complete"
    lc["current_phase_id"] = None
    return lc


def _profile(level="intermediate", target=75):
    from romyq.profile import config as prof_config, COMPLEXITY_CONFIG
    cfg = prof_config(level)
    cfg["readiness_target"] = target
    return cfg


def _readiness(overall=80):
    return {"overall": overall, "label": "Ready", "categories": {}}


def _state(**kwargs):
    base = {
        "status": "running",
        "consecutive_failures": 0,
        "paused": False,
        "pause_requested": False,
    }
    base.update(kwargs)
    return base


# ── _make ─────────────────────────────────────────────────────────────────────

class TestMake:
    def test_contains_recommendation(self):
        r = _make("Continue", "reason")
        assert r["recommendation"] == "Continue"

    def test_contains_reason(self):
        r = _make("Stop", "done!")
        assert r["reason"] == "done!"

    def test_readiness_rounded(self):
        r = _make("Continue", "x", readiness=73.567)
        assert r["readiness"] == 73.6

    def test_empty_criteria_defaults(self):
        r = _make("Continue", "x")
        assert r["done_criteria_met"] == []
        assert r["done_criteria_pending"] == []


# ── recommend — basic cases ───────────────────────────────────────────────────

class TestRecommend:
    def test_continue_when_in_progress(self):
        lc = _lifecycle([
            {"id": 1, "name": "Setup", "tasks": [
                {"id": "1.1", "text": "Init project"},
                {"id": "1.2", "text": "Set up deps"},
            ]},
        ], done_criteria=["software runs"])
        result = recommend(_readiness(50), lc, _state(), _profile(target=75))
        assert result["recommendation"] == "Continue"

    def test_stop_when_all_done(self):
        lc = _all_complete_lifecycle()
        lc["done_criteria"] = []
        result = recommend(_readiness(80), lc, _state(), _profile(target=75))
        assert result["recommendation"] == "Stop"

    def test_pause_when_paused(self):
        lc = _lifecycle([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        result = recommend(_readiness(80), lc, _state(paused=True), _profile())
        assert result["recommendation"] == "Pause"

    def test_pause_when_pause_requested(self):
        lc = _lifecycle([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        result = recommend(_readiness(80), lc, _state(pause_requested=True), _profile())
        assert result["recommendation"] == "Pause"

    def test_review_when_too_many_failures(self):
        lc = _lifecycle([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        result = recommend(_readiness(80), lc, _state(consecutive_failures=5), _profile())
        assert result["recommendation"] == "Review"

    def test_review_when_phases_done_but_criteria_pending(self):
        lc = _all_complete_lifecycle()
        lc["done_criteria"] = ["software runs", "tests pass"]
        result = recommend(_readiness(80), lc, _state(), _profile(target=75))
        assert result["recommendation"] == "Review"

    def test_continue_high_readiness_but_phases_remaining(self):
        lc = _lifecycle([
            {"id": 1, "name": "Setup", "tasks": [{"id": "1.1", "text": "Initialize project structure"}]},
            {"id": 2, "name": "Core", "tasks": [{"id": "2.1", "text": "Implement core logic"}]},
        ])
        lc["phases"][0]["status"] = "complete"
        result = recommend(_readiness(80), lc, _state(), _profile(target=75))
        assert result["recommendation"] == "Continue"

    def test_pause_has_higher_priority_than_failures(self):
        lc = _lifecycle([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        result = recommend(_readiness(80), lc, _state(paused=True, consecutive_failures=10), _profile())
        assert result["recommendation"] == "Pause"

    def test_result_has_phases_complete(self):
        lc = _lifecycle([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        result = recommend(_readiness(50), lc, _state(), _profile())
        assert "phases_complete" in result
        assert "total_phases" in result

    def test_readiness_in_result(self):
        lc = _lifecycle([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        result = recommend(_readiness(67), lc, _state(), _profile())
        assert result["readiness"] == 67.0


# ── recommend — threshold sensitivity ────────────────────────────────────────

class TestRecommendThreshold:
    def test_stop_exactly_at_threshold(self):
        lc = _all_complete_lifecycle()
        lc["done_criteria"] = []
        result = recommend(_readiness(75), lc, _state(), _profile(target=75))
        assert result["recommendation"] == "Stop"

    def test_continue_just_below_threshold(self):
        lc = _all_complete_lifecycle()
        lc["done_criteria"] = []
        result = recommend(_readiness(74), lc, _state(), _profile(target=75))
        assert result["recommendation"] in ("Continue", "Review")

    def test_basic_threshold_is_lower(self):
        lc = _all_complete_lifecycle()
        lc["done_criteria"] = []
        result = recommend(_readiness(60), lc, _state(), _profile("basic", target=60))
        assert result["recommendation"] == "Stop"

    def test_advanced_threshold_higher(self):
        lc = _all_complete_lifecycle()
        lc["done_criteria"] = []
        result = recommend(_readiness(80), lc, _state(), _profile("advanced", target=90))
        assert result["recommendation"] in ("Continue", "Review")


# ── _check_done_criteria ──────────────────────────────────────────────────────

class TestCheckDoneCriteria:
    def test_empty_criteria_returns_empty(self):
        lc = _lifecycle([{"id": 1, "name": "P", "tasks": [{"id": "1.1", "text": "task"}]}])
        met, pending = _check_done_criteria([], lc, {})
        assert met == []
        assert pending == []

    def test_software_runs_when_core_phase_complete(self):
        lc = _lifecycle([{"id": 1, "name": "Core Implementation", "tasks": [
            {"id": "1.1", "text": "implement core logic", "status": "complete", "completed_at": None}
        ]}])
        lc["phases"][0]["status"] = "complete"
        met, pending = _check_done_criteria(["software runs"], lc, {})
        assert "software runs" in met

    def test_tests_pass_when_testing_phase_complete(self):
        lc = _lifecycle([{"id": 1, "name": "Testing", "tasks": [
            {"id": "1.1", "text": "write tests", "status": "complete", "completed_at": None}
        ]}])
        lc["phases"][0]["status"] = "complete"
        met, pending = _check_done_criteria(["tests pass"], lc, {})
        assert "tests pass" in met

    def test_pending_criterion_not_met(self):
        lc = _lifecycle([{"id": 1, "name": "Setup", "tasks": [{"id": "1.1", "text": "init"}]}])
        met, pending = _check_done_criteria(["tests pass"], lc, {})
        assert "tests pass" in pending

    def test_readme_satisfied_by_completed_task(self):
        lc = _lifecycle([{"id": 1, "name": "Documentation", "tasks": [
            {"id": "1.1", "text": "write readme", "status": "complete", "completed_at": None}
        ]}])
        lc["phases"][0]["status"] = "complete"
        met, pending = _check_done_criteria(["README exists"], lc, {})
        assert "README exists" in met

    def test_security_satisfied_by_capability(self):
        lc = _lifecycle([{"id": 1, "name": "Security", "tasks": [
            {"id": "1.1", "text": "add auth", "status": "complete", "completed_at": None}
        ]}])
        lc["phases"][0]["status"] = "complete"
        state = {"capabilities": {"Security": {"status": "complete"}}}
        met, pending = _check_done_criteria(["security requirements met"], lc, state)
        assert "security requirements met" in met

    def test_deployment_satisfied_by_phase(self):
        lc = _lifecycle([{"id": 1, "name": "Deployment", "tasks": [
            {"id": "1.1", "text": "create CI pipeline", "status": "complete", "completed_at": None}
        ]}])
        lc["phases"][0]["status"] = "complete"
        met, pending = _check_done_criteria(["deployment ready"], lc, {})
        assert "deployment ready" in met


# ── format_recommendation ─────────────────────────────────────────────────────

class TestFormatRecommendation:
    def test_returns_string(self):
        r = _make("Continue", "in progress", 50, 1, 3)
        result = format_recommendation(r)
        assert isinstance(result, str)

    def test_contains_recommendation(self):
        r = _make("Stop", "all done", 90, 3, 3)
        result = format_recommendation(r)
        assert "Stop" in result

    def test_contains_reason(self):
        r = _make("Review", "consecutive failures", 40, 0, 2)
        result = format_recommendation(r)
        assert "consecutive failures" in result

    def test_contains_readiness_percentage(self):
        r = _make("Continue", "going", 73.0, 1, 4)
        result = format_recommendation(r)
        assert "73" in result

    def test_contains_phase_info(self):
        r = _make("Continue", "going", 50, 2, 4)
        result = format_recommendation(r)
        assert "2/4" in result

    def test_shows_met_criteria(self):
        r = _make("Stop", "done", 90, 3, 3, criteria_met=["software runs"])
        result = format_recommendation(r)
        assert "software runs" in result

    def test_shows_pending_criteria(self):
        r = _make("Review", "pending", 80, 2, 3, criteria_pending=["tests pass"])
        result = format_recommendation(r)
        assert "tests pass" in result

    def test_stop_has_stop_icon(self):
        r = _make("Stop", "done")
        result = format_recommendation(r)
        assert "■" in result

    def test_pause_has_pause_icon(self):
        r = _make("Pause", "waiting")
        result = format_recommendation(r)
        assert "⏸" in result

    def test_review_has_warning_icon(self):
        r = _make("Review", "issues")
        result = format_recommendation(r)
        assert "⚠" in result
