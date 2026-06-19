"""Tests for romyq.planning — build_planning_context()."""
import json
import os
import tempfile
from pathlib import Path

import pytest

from romyq.planning import build_planning_context


# ── helpers ───────────────────────────────────────────────────────────────────

def _write_history(path: str, entries: list[dict]) -> None:
    Path(path).write_text(json.dumps(entries), encoding="utf-8")


def _write_findings(path: str, items: list[dict]) -> None:
    Path(path).write_text(json.dumps(items), encoding="utf-8")


def _state(**kwargs) -> dict:
    base = {
        "phase": "idle",
        "current_task_key": "",
        "current_task_attempts": 0,
        "max_task_attempts": 3,
        "last_failure_reason": "",
        "last_validation_evidence": [],
    }
    base.update(kwargs)
    return base


class TestBuildPlanningContext:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.h_path = os.path.join(self.tmpdir, "history.json")
        self.f_path = os.path.join(self.tmpdir, "findings.json")

    def _run(self, state=None, context_text="", max_failures=10, **state_kw):
        if state is None:
            state = _state(**state_kw)
        return build_planning_context(
            state=state,
            findings_path=self.f_path,
            history_path=self.h_path,
            context_text=context_text,
            max_failures=max_failures,
        )

    # ── Empty state returns empty ─────────────────────────────────────────────

    def test_empty_state_returns_empty_string(self):
        assert self._run() == ""

    # ── Context text inclusion ────────────────────────────────────────────────

    def test_includes_context_text(self):
        result = self._run(context_text="# Repository Context\npython project\n")
        assert "Repository Context" in result
        assert "python project" in result

    def test_empty_context_text_not_included(self):
        result = self._run(context_text="   ")
        assert "Repository Context" not in result

    # ── Recent failures ───────────────────────────────────────────────────────

    def test_includes_recent_failures(self):
        entries = [
            {"task": "add tests", "success": False,
             "timestamp": "2026-01-01T00:00:00+00:00",
             "mode": "impl", "commit": "", "validation_reason": "tests failed"},
        ]
        _write_history(self.h_path, entries)
        result = self._run()
        assert "tests failed" in result
        assert "add tests" in result

    def test_does_not_include_successful_tasks_in_failures(self):
        entries = [
            {"task": "fix thing", "success": True,
             "timestamp": "2026-01-01T00:00:00+00:00",
             "mode": "impl", "commit": "a", "validation_reason": "ok"},
        ]
        _write_history(self.h_path, entries)
        result = self._run()
        # fix thing was a success — should not appear in recent failures section
        assert "Recent Failures" not in result

    def test_caps_failures_at_max_failures(self):
        entries = [
            {"task": f"task {i}", "success": False,
             "timestamp": "2026-01-01T00:00:00+00:00",
             "mode": "impl", "commit": "", "validation_reason": f"reason {i}"}
            for i in range(15)
        ]
        _write_history(self.h_path, entries)
        result = self._run(max_failures=5)
        # Only the last 5 should appear
        failure_count = result.count("reason ")
        assert failure_count <= 5

    # ── Blocked task warning ──────────────────────────────────────────────────

    def test_blocked_task_section_shown(self):
        result = self._run(
            current_task_key="abc123def456",
            current_task_attempts=3,
            max_task_attempts=3,
        )
        assert "BLOCKED" in result
        assert "abc123" in result

    def test_blocked_task_shows_last_reason(self):
        result = self._run(
            current_task_key="abc123",
            current_task_attempts=3,
            max_task_attempts=3,
            last_failure_reason="compilation error in main.py",
        )
        assert "compilation error" in result

    def test_not_blocked_no_blocked_section(self):
        result = self._run(
            current_task_key="abc123",
            current_task_attempts=2,
            max_task_attempts=3,
        )
        assert "BLOCKED" not in result

    def test_no_key_no_blocked_section(self):
        result = self._run(
            current_task_key="",
            current_task_attempts=3,
            max_task_attempts=3,
        )
        assert "BLOCKED" not in result

    # ── Validation evidence ───────────────────────────────────────────────────

    def test_includes_validation_evidence(self):
        result = self._run(
            last_validation_evidence=["exit code: 1", "tests: 3 failed"],
        )
        assert "exit code: 1" in result
        assert "tests: 3 failed" in result

    def test_empty_evidence_not_included(self):
        result = self._run(last_validation_evidence=[])
        assert "Validator Evidence" not in result

    def test_caps_evidence_at_10_lines(self):
        evidence = [f"line {i}" for i in range(20)]
        result = self._run(last_validation_evidence=evidence)
        shown = [f"line {i}" for i in range(10)]
        hidden = [f"line {i}" for i in range(10, 20)]
        assert all(s in result for s in shown)
        assert not all(h in result for h in hidden)

    # ── Findings ──────────────────────────────────────────────────────────────

    def test_includes_unresolved_findings(self):
        items = [{"title": "Missing auth check", "severity": "high", "resolved": False,
                  "description": "", "created_at": ""}]
        _write_findings(self.f_path, items)
        result = self._run()
        assert "Missing auth check" in result

    def test_resolved_findings_not_included(self):
        items = [{"title": "Old issue", "severity": "low", "resolved": True,
                  "description": "", "created_at": ""}]
        _write_findings(self.f_path, items)
        result = self._run()
        assert "Old issue" not in result

    def test_empty_findings_no_section(self):
        _write_findings(self.f_path, [])
        result = self._run()
        assert "Unresolved Findings" not in result

    # ── Output structure ──────────────────────────────────────────────────────

    def test_output_contains_separator(self):
        result = self._run(context_text="# Context\nhi")
        assert "─" * 30 in result

    def test_returns_string_always(self):
        assert isinstance(self._run(), str)

    def test_combined_sections(self):
        entries = [
            {"task": "broken task", "success": False,
             "timestamp": "2026-01-01T00:00:00+00:00",
             "mode": "impl", "commit": "", "validation_reason": "test failure"},
        ]
        _write_history(self.h_path, entries)
        items = [{"title": "Missing tests", "severity": "medium", "resolved": False,
                  "description": "", "created_at": ""}]
        _write_findings(self.f_path, items)
        result = self._run(
            context_text="# Repo\npython",
            last_validation_evidence=["exit=1"],
        )
        assert "Repo" in result
        assert "broken task" in result or "test failure" in result
        assert "Missing tests" in result
        assert "exit=1" in result
