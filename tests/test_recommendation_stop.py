"""Regression tests for lifecycle-completion Stop logic in recommendation.py.

These tests guard against the production bug where readiness < threshold
blocked the Stop recommendation even when all lifecycle tasks were done.
"""
from __future__ import annotations

import pytest

from romyq.lifecycle import _build_lifecycle, _validate_phases
from romyq.recommendation import recommend
from romyq.profile import config as prof_config


# ── helpers ───────────────────────────────────────────────────────────────────

def _all_complete(phases_raw, done_criteria=None, complexity="basic"):
    phases = _validate_phases(phases_raw)
    lc = _build_lifecycle(phases, "test mission", complexity, done_criteria or ["software runs"])
    for phase in lc["phases"]:
        phase["status"] = "complete"
        for task in phase["tasks"]:
            task["status"] = "complete"
    lc["current_phase_id"] = None
    return lc


def _partial(phases_raw, done_criteria=None, complexity="basic"):
    phases = _validate_phases(phases_raw)
    lc = _build_lifecycle(phases, "test mission", complexity, done_criteria or ["software runs"])
    # Leave first phase pending so not all_done
    return lc


_TWO_PHASES = [
    {"id": 1, "name": "Core Calculator", "tasks": [
        {"id": "1.1", "text": "Implement calculator engine"},
        {"id": "1.2", "text": "Add arithmetic operations"},
        {"id": "1.3", "text": "Create HTML/JS interface"},
    ]},
    {"id": 2, "name": "Pokemon 3D Theme", "tasks": [
        {"id": "2.1", "text": "Add Three.js dependency"},
        {"id": "2.2", "text": "Create Pikachu 3D model"},
        {"id": "2.3", "text": "Wire 3D scene to calculator"},
    ]},
]

def _state(**kw):
    base = {"status": "running", "consecutive_failures": 0, "paused": False, "pause_requested": False}
    base.update(kw)
    return base

def _rdns(overall):
    return {"overall": overall, "label": "x", "categories": {}}


# ── FIX 1 regression: readiness must not block lifecycle-complete Stop ─────────

class TestStopWhenLifecycleComplete:
    def test_stop_basic_low_readiness(self):
        """Basic project: all phases done, criteria met, readiness=7% → Stop."""
        lc = _all_complete(_TWO_PHASES, done_criteria=["software runs"], complexity="basic")
        profile = prof_config("basic")
        rec = recommend(_rdns(7), lc, _state(), profile)
        assert rec["recommendation"] == "Stop"

    def test_stop_basic_zero_readiness(self):
        """Readiness 0% must not block Stop when lifecycle is complete."""
        lc = _all_complete(_TWO_PHASES, done_criteria=["software runs"], complexity="basic")
        profile = prof_config("basic")
        rec = recommend(_rdns(0), lc, _state(), profile)
        assert rec["recommendation"] == "Stop"

    def test_stop_basic_target_not_reached(self):
        """basic readiness_target=60, overall=30 — still Stop when all done."""
        lc = _all_complete(_TWO_PHASES, done_criteria=["software runs"], complexity="basic")
        profile = prof_config("basic")
        assert profile["readiness_target"] == 60
        rec = recommend(_rdns(30), lc, _state(), profile)
        assert rec["recommendation"] == "Stop"

    def test_stop_reason_mentions_phases_complete(self):
        lc = _all_complete(_TWO_PHASES, done_criteria=["software runs"], complexity="basic")
        profile = prof_config("basic")
        rec = recommend(_rdns(7), lc, _state(), profile)
        assert "phases complete" in rec["reason"].lower() or "all phases" in rec["reason"].lower()

    def test_stop_phases_count_correct(self):
        lc = _all_complete(_TWO_PHASES, done_criteria=["software runs"], complexity="basic")
        profile = prof_config("basic")
        rec = recommend(_rdns(7), lc, _state(), profile)
        assert rec["phases_complete"] == 2
        assert rec["total_phases"] == 2

    def test_stop_criteria_reported(self):
        lc = _all_complete(_TWO_PHASES, done_criteria=["software runs"], complexity="basic")
        profile = prof_config("basic")
        rec = recommend(_rdns(7), lc, _state(), profile)
        assert "software runs" in rec["done_criteria_met"]
        assert rec["done_criteria_pending"] == []


class TestStopIntermediateAllCriteriaMet:
    """Intermediate profile: done criteria include tests/readme — satisfied via phase names."""

    def _intermediate_lc_with_test_phase(self):
        phases = _validate_phases([
            {"id": 1, "name": "Core Implementation", "tasks": [
                {"id": "1.1", "text": "Implement core logic"},
                {"id": "1.2", "text": "Add error handling"},
            ]},
            {"id": 2, "name": "Testing", "tasks": [
                {"id": "2.1", "text": "Write unit tests"},
                {"id": "2.2", "text": "Write integration tests"},
            ]},
            {"id": 3, "name": "Documentation", "tasks": [
                {"id": "3.1", "text": "Create README with examples"},
            ]},
        ])
        lc = _build_lifecycle(
            phases, "test", "intermediate",
            ["software runs", "tests pass", "README exists"],
        )
        for phase in lc["phases"]:
            phase["status"] = "complete"
            for task in phase["tasks"]:
                task["status"] = "complete"
        lc["current_phase_id"] = None
        return lc

    def test_stop_intermediate_all_done(self):
        lc = self._intermediate_lc_with_test_phase()
        profile = prof_config("intermediate")
        # readiness well below 75 target — should still Stop
        rec = recommend(_rdns(25), lc, _state(), profile)
        assert rec["recommendation"] == "Stop"

    def test_stop_intermediate_criteria_in_met_list(self):
        lc = self._intermediate_lc_with_test_phase()
        profile = prof_config("intermediate")
        rec = recommend(_rdns(25), lc, _state(), profile)
        assert rec["done_criteria_pending"] == []


class TestReviewWhenCriteriaPending:
    """All phases complete but done criteria not yet satisfied → Review, not Stop."""

    def test_review_when_criteria_pending(self):
        """Intermediate: all done but no Testing/README phase → criteria pending → Review."""
        phases = _validate_phases([
            {"id": 1, "name": "Core Implementation", "tasks": [
                {"id": "1.1", "text": "Implement core logic"},
            ]},
        ])
        lc = _build_lifecycle(
            phases, "test", "intermediate",
            ["software runs", "tests pass", "README exists"],
        )
        for phase in lc["phases"]:
            phase["status"] = "complete"
            for task in phase["tasks"]:
                task["status"] = "complete"
        lc["current_phase_id"] = None
        profile = prof_config("intermediate")
        rec = recommend(_rdns(5), lc, _state(), profile)
        # "tests pass" and "README exists" are not satisfiable from phase names alone
        assert rec["recommendation"] == "Review"
        assert len(rec["done_criteria_pending"]) > 0

    def test_continue_when_phases_incomplete(self):
        """Phases still in progress — must Continue, never Stop."""
        lc = _partial(_TWO_PHASES, done_criteria=["software runs"], complexity="basic")
        profile = prof_config("basic")
        rec = recommend(_rdns(80), lc, _state(), profile)
        assert rec["recommendation"] == "Continue"

    def test_continue_when_no_lifecycle(self):
        """Empty lifecycle → Continue."""
        from romyq.lifecycle import _empty
        lc = _empty()
        profile = prof_config("basic")
        rec = recommend(_rdns(80), lc, _state(), profile)
        assert rec["recommendation"] == "Continue"


class TestPauseAndReviewTakePriority:
    """Pause and Review conditions must still fire before Stop."""

    def test_pause_overrides_lifecycle_complete(self):
        lc = _all_complete(_TWO_PHASES, done_criteria=["software runs"])
        profile = prof_config("basic")
        rec = recommend(_rdns(0), lc, _state(paused=True), profile)
        assert rec["recommendation"] == "Pause"

    def test_review_on_consecutive_failures(self):
        lc = _all_complete(_TWO_PHASES, done_criteria=["software runs"])
        profile = prof_config("basic")
        rec = recommend(_rdns(0), lc, _state(consecutive_failures=5), profile)
        assert rec["recommendation"] == "Review"


# ── Pokemon calculator exact scenario ─────────────────────────────────────────

class TestPokemonCalculatorScenario:
    """Reproduce the exact production bug: basic 2-phase/6-task lifecycle at 7% readiness."""

    def _build_calculator_lc(self):
        phases = _validate_phases([
            {"id": 1, "name": "Core Calculator", "tasks": [
                {"id": "1.1", "text": "Implement calculator engine with basic arithmetic"},
                {"id": "1.2", "text": "Build the HTML/CSS user interface"},
                {"id": "1.3", "text": "Connect engine to UI and add event listeners"},
            ]},
            {"id": 2, "name": "Pokemon 3D Theme", "tasks": [
                {"id": "2.1", "text": "Add Three.js and set up 3D scene"},
                {"id": "2.2", "text": "Create rotating Pikachu 3D model"},
                {"id": "2.3", "text": "Integrate 3D scene with calculator interface"},
            ]},
        ])
        done_criteria = ["software runs"]
        lc = _build_lifecycle(phases, "a calculator with pokemon 3d theme", "basic", done_criteria)
        return lc

    def test_continue_during_execution(self):
        """Mid-run: only phase 1 active, phase 2 pending → Continue."""
        lc = self._build_calculator_lc()
        profile = prof_config("basic")
        rec = recommend(_rdns(7), lc, _state(), profile)
        assert rec["recommendation"] == "Continue"

    def test_stop_after_all_6_tasks_complete(self):
        """The bug: after task 6, recommendation must be Stop, not Continue."""
        lc = self._build_calculator_lc()
        # Mark all tasks complete (as the loop does after task 6)
        for phase in lc["phases"]:
            phase["status"] = "complete"
            for task in phase["tasks"]:
                task["status"] = "complete"
        lc["current_phase_id"] = None
        profile = prof_config("basic")
        # Production readiness was 7% — must not block Stop
        rec = recommend(_rdns(7), lc, _state(), profile)
        assert rec["recommendation"] == "Stop", (
            f"Expected Stop but got {rec['recommendation']}: {rec['reason']}"
        )

    def test_task_count_before_stop(self):
        """All 6 tasks complete → 2/2 phases → Stop."""
        lc = self._build_calculator_lc()
        for phase in lc["phases"]:
            phase["status"] = "complete"
            for task in phase["tasks"]:
                task["status"] = "complete"
        lc["current_phase_id"] = None
        profile = prof_config("basic")
        rec = recommend(_rdns(7), lc, _state(), profile)
        assert rec["phases_complete"] == 2
        assert rec["total_phases"] == 2
