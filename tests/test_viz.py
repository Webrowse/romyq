"""Tests for romyq/viz.py — pure formatting functions."""
from __future__ import annotations

import pytest
from romyq.viz import (
    progress_bar,
    format_phase_bars,
    format_overall_bar,
    format_architecture_flow,
    format_lifecycle_preview,
    format_project_overview,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _phase(name, status="pending", pct=0, tasks=None, completed=0):
    t = tasks or [{"id": f"t{i}", "text": f"Task item {i}", "status": "pending"} for i in range(3)]
    return {
        "id": 1,
        "name": name,
        "status": status,
        "percentage_complete": pct,
        "total_tasks": len(t),
        "completed_tasks": completed,
        "tasks": t,
    }


def _lifecycle(phases=None, done_criteria=None):
    return {
        "phases": phases or [],
        "done_criteria": done_criteria or [],
    }


# ── progress_bar ──────────────────────────────────────────────────────────────

class TestProgressBar:
    def test_zero_percent(self):
        bar = progress_bar(0)
        assert bar == "░" * 12

    def test_hundred_percent(self):
        bar = progress_bar(100)
        assert bar == "█" * 12

    def test_fifty_percent(self):
        bar = progress_bar(50, width=10)
        assert bar == "█" * 5 + "░" * 5

    def test_width_respected(self):
        bar = progress_bar(0, width=20)
        assert len(bar) == 20

    def test_custom_fill_chars(self):
        bar = progress_bar(100, width=4, fill="X", empty="-")
        assert bar == "XXXX"

    def test_custom_empty_chars(self):
        bar = progress_bar(0, width=4, fill="X", empty="-")
        assert bar == "----"

    def test_clamps_below_zero(self):
        bar = progress_bar(-10, width=4)
        assert bar == "░░░░"

    def test_clamps_above_hundred(self):
        bar = progress_bar(150, width=4)
        assert bar == "████"

    def test_25_percent(self):
        bar = progress_bar(25, width=8)
        assert bar == "██░░░░░░"

    def test_75_percent(self):
        bar = progress_bar(75, width=8)
        assert bar == "██████░░"

    def test_default_width_12(self):
        bar = progress_bar(50)
        assert len(bar) == 12

    def test_returns_string(self):
        assert isinstance(progress_bar(50), str)


# ── format_phase_bars ─────────────────────────────────────────────────────────

class TestFormatPhaseBars:
    def test_empty_lifecycle(self):
        result = format_phase_bars(_lifecycle())
        assert "no lifecycle" in result.lower()

    def test_pending_phase_shows_square(self):
        lc = _lifecycle([_phase("Setup", status="pending", pct=0)])
        result = format_phase_bars(lc)
        assert "□" in result

    def test_active_phase_shows_arrow(self):
        lc = _lifecycle([_phase("Setup", status="active", pct=30)])
        result = format_phase_bars(lc)
        assert "→" in result

    def test_complete_phase_shows_checkmark(self):
        lc = _lifecycle([_phase("Setup", status="complete", pct=100)])
        result = format_phase_bars(lc)
        assert "✓" in result

    def test_phase_name_in_output(self):
        lc = _lifecycle([_phase("My Phase Name", status="active", pct=50)])
        result = format_phase_bars(lc)
        assert "My Phase Name" in result

    def test_percentage_in_output(self):
        lc = _lifecycle([_phase("Setup", status="active", pct=42)])
        result = format_phase_bars(lc)
        assert "42%" in result or " 42" in result

    def test_complete_phase_shows_100_pct(self):
        lc = _lifecycle([_phase("Setup", status="complete")])
        result = format_phase_bars(lc)
        assert "100%" in result

    def test_multiple_phases(self):
        lc = _lifecycle([
            _phase("Phase A", status="complete"),
            _phase("Phase B", status="active", pct=50),
            _phase("Phase C", status="pending"),
        ])
        lines = format_phase_bars(lc).splitlines()
        assert len(lines) == 3

    def test_bar_chars_present(self):
        lc = _lifecycle([_phase("Setup", status="active", pct=50)])
        result = format_phase_bars(lc)
        assert "█" in result or "░" in result

    def test_custom_bar_width(self):
        lc = _lifecycle([_phase("Setup", status="active", pct=100)])
        result = format_phase_bars(lc, bar_width=20)
        assert "█" * 20 in result

    def test_returns_string(self):
        lc = _lifecycle([_phase("Setup")])
        assert isinstance(format_phase_bars(lc), str)


# ── format_overall_bar ────────────────────────────────────────────────────────

class TestFormatOverallBar:
    def test_empty_lifecycle(self):
        result = format_overall_bar(_lifecycle())
        assert "0%" in result

    def test_zero_tasks_complete(self):
        lc = _lifecycle([_phase("Setup", tasks=[
            {"id": "t1", "text": "Do this", "status": "pending"},
            {"id": "t2", "text": "Do that", "status": "pending"},
        ], completed=0)])
        result = format_overall_bar(lc)
        assert "0%" in result or "0/2" in result

    def test_all_tasks_complete(self):
        p = _phase("Setup", completed=3)
        p["total_tasks"] = 3
        result = format_overall_bar(_lifecycle([p]))
        assert "100%" in result

    def test_contains_overall_label(self):
        result = format_overall_bar(_lifecycle([_phase("Setup")]))
        assert "Overall" in result

    def test_task_count_in_output(self):
        p = _phase("Setup", completed=1)
        p["total_tasks"] = 3
        result = format_overall_bar(_lifecycle([p]))
        assert "1/3" in result or "1" in result

    def test_returns_string(self):
        assert isinstance(format_overall_bar(_lifecycle()), str)

    def test_bar_chars_present(self):
        p = _phase("Setup", completed=1)
        p["total_tasks"] = 4
        result = format_overall_bar(_lifecycle([p]))
        assert "█" in result or "░" in result


# ── format_architecture_flow ──────────────────────────────────────────────────

class TestFormatArchitectureFlow:
    def test_empty_lifecycle(self):
        result = format_architecture_flow(_lifecycle())
        assert "no lifecycle" in result.lower()

    def test_phase_name_in_output(self):
        lc = _lifecycle([_phase("Foundation")])
        result = format_architecture_flow(lc)
        assert "Foundation" in result

    def test_arrow_between_phases(self):
        lc = _lifecycle([_phase("Phase A"), _phase("Phase B")])
        result = format_architecture_flow(lc)
        assert "↓" in result

    def test_no_arrow_after_last_phase(self):
        lc = _lifecycle([_phase("Only Phase")])
        result = format_architecture_flow(lc)
        assert "↓" not in result

    def test_phase_numbering(self):
        lc = _lifecycle([_phase("Alpha"), _phase("Beta"), _phase("Gamma")])
        result = format_architecture_flow(lc)
        assert "1." in result
        assert "2." in result
        assert "3." in result

    def test_complete_status_shown(self):
        lc = _lifecycle([_phase("Done", status="complete")])
        result = format_architecture_flow(lc)
        assert "complete" in result

    def test_active_status_shown(self):
        lc = _lifecycle([_phase("Active", status="active", pct=50)])
        result = format_architecture_flow(lc)
        assert "active" in result

    def test_task_count_in_output(self):
        p = _phase("Build")
        result = format_architecture_flow(_lifecycle([p]))
        assert "task" in result

    def test_returns_multiline_for_multiple_phases(self):
        lc = _lifecycle([_phase("A"), _phase("B")])
        result = format_architecture_flow(lc)
        assert "\n" in result

    def test_returns_string(self):
        assert isinstance(format_architecture_flow(_lifecycle()), str)


# ── format_lifecycle_preview ──────────────────────────────────────────────────

class TestFormatLifecyclePreview:
    def test_empty_lifecycle(self):
        result = format_lifecycle_preview(_lifecycle())
        assert "no lifecycle" in result.lower()

    def test_phase_name_in_preview(self):
        lc = _lifecycle([_phase("Foundation")])
        result = format_lifecycle_preview(lc)
        assert "Foundation" in result

    def test_phase_numbering(self):
        lc = _lifecycle([_phase("Alpha"), _phase("Beta")])
        result = format_lifecycle_preview(lc)
        assert "1." in result
        assert "2." in result

    def test_task_count_in_preview(self):
        lc = _lifecycle([_phase("Build")])
        result = format_lifecycle_preview(lc)
        assert "task" in result

    def test_total_tasks_shown(self):
        lc = _lifecycle([
            _phase("A", tasks=[{"id": "t1", "text": "Item one", "status": "pending"}]),
            _phase("B", tasks=[{"id": "t2", "text": "Item two", "status": "pending"}, {"id": "t3", "text": "Item three", "status": "pending"}]),
        ])
        result = format_lifecycle_preview(lc)
        assert "3" in result or "Total" in result

    def test_done_criteria_shown(self):
        lc = _lifecycle([_phase("A")], done_criteria=["Tests pass", "CI green"])
        result = format_lifecycle_preview(lc)
        assert "Tests pass" in result or "Done criteria" in result

    def test_no_criteria_section_when_none(self):
        lc = _lifecycle([_phase("A")], done_criteria=[])
        result = format_lifecycle_preview(lc)
        assert "Done criteria" not in result

    def test_returns_string(self):
        assert isinstance(format_lifecycle_preview(_lifecycle()), str)


# ── format_project_overview ───────────────────────────────────────────────────

class TestFormatProjectOverview:
    def _rdns(self, overall=0):
        return {"overall": overall, "label": "Not Ready", "categories": {}}

    def _rec(self, r="Continue"):
        return {"recommendation": r, "reason": ""}

    def _prof(self, label="Intermediate", target=75):
        return {"label": label, "readiness_target": target}

    def test_project_name_in_output(self):
        lc = _lifecycle([_phase("A")])
        result = format_project_overview(lc, self._rdns(), self._rec(), self._prof(), "My Project")
        assert "My Project" in result

    def test_complexity_in_output(self):
        lc = _lifecycle([_phase("A")])
        result = format_project_overview(lc, self._rdns(), self._rec(), self._prof("Advanced"), "")
        assert "Advanced" in result

    def test_recommendation_in_output(self):
        lc = _lifecycle([_phase("A")])
        result = format_project_overview(lc, self._rdns(), self._rec("Stop"), self._prof(), "")
        assert "Stop" in result

    def test_readiness_in_output(self):
        lc = _lifecycle([_phase("A")])
        result = format_project_overview(lc, self._rdns(overall=72), self._rec(), self._prof(), "")
        assert "72" in result

    def test_target_in_output(self):
        lc = _lifecycle([_phase("A")])
        result = format_project_overview(lc, self._rdns(), self._rec(), self._prof(target=90), "")
        assert "90" in result

    def test_phases_count_in_output(self):
        lc = _lifecycle([_phase("A"), _phase("B"), _phase("C")])
        result = format_project_overview(lc, self._rdns(), self._rec(), self._prof(), "")
        assert "3" in result

    def test_empty_lifecycle_no_crash(self):
        result = format_project_overview(_lifecycle(), self._rdns(), self._rec(), self._prof(), "")
        assert isinstance(result, str)

    def test_returns_string(self):
        lc = _lifecycle([_phase("A")])
        result = format_project_overview(lc, self._rdns(), self._rec(), self._prof(), "")
        assert isinstance(result, str)
