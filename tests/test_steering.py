"""Tests for romyq.steering — operator instruction events."""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from romyq import steering as steering_mod


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def events_file(tmp_path):
    p = tmp_path / "events.log"
    p.write_text("", encoding="utf-8")
    return str(p)


def _write_event(events_path: str, event_type: str, **kwargs) -> None:
    from romyq.events import emit
    emit(events_path, event_type, **kwargs)


# ── TestRecordInstruction ─────────────────────────────────────────────────────

class TestRecordInstruction:
    def test_records_instruction_to_log(self, events_file):
        steering_mod.record_instruction(events_file, "use PostgreSQL")
        content = Path(events_file).read_text()
        assert "operator_instruction" in content

    def test_instruction_text_stored(self, events_file):
        steering_mod.record_instruction(events_file, "focus on backend APIs")
        content = Path(events_file).read_text()
        assert "focus on backend APIs" in content

    def test_empty_instruction_not_recorded(self, events_file):
        steering_mod.record_instruction(events_file, "   ")
        content = Path(events_file).read_text()
        assert content.strip() == ""

    def test_strips_whitespace(self, events_file):
        steering_mod.record_instruction(events_file, "  add JWT auth  ")
        content = Path(events_file).read_text()
        data = json.loads(content.strip())
        assert data["instruction"] == "add JWT auth"

    def test_truncates_long_instruction(self, events_file):
        long = "x" * 600
        steering_mod.record_instruction(events_file, long)
        content = Path(events_file).read_text()
        data = json.loads(content.strip())
        assert len(data["instruction"]) <= 500

    def test_records_event_type_constant(self, events_file):
        steering_mod.record_instruction(events_file, "test")
        content = Path(events_file).read_text()
        data = json.loads(content.strip())
        assert data["event"] == steering_mod.OPERATOR_INSTRUCTION

    def test_multiple_instructions_appended(self, events_file):
        steering_mod.record_instruction(events_file, "first")
        steering_mod.record_instruction(events_file, "second")
        lines = [l for l in Path(events_file).read_text().splitlines() if l.strip()]
        assert len(lines) == 2

    def test_missing_events_path_does_not_raise(self, tmp_path):
        # emit() catches exceptions — should not propagate
        steering_mod.record_instruction(str(tmp_path / "events.log"), "test")


# ── TestRecentInstructions ────────────────────────────────────────────────────

class TestRecentInstructions:
    def test_returns_empty_when_no_events(self, events_file):
        result = steering_mod.recent_instructions(events_file)
        assert result == []

    def test_returns_empty_when_no_operator_events(self, events_file):
        _write_event(events_file, "task_started", key="abc")
        result = steering_mod.recent_instructions(events_file)
        assert result == []

    def test_returns_recorded_instructions(self, events_file):
        steering_mod.record_instruction(events_file, "use Redis")
        result = steering_mod.recent_instructions(events_file)
        assert "use Redis" in result

    def test_filters_non_instruction_events(self, events_file):
        _write_event(events_file, "task_started", key="abc")
        steering_mod.record_instruction(events_file, "my instruction")
        _write_event(events_file, "validator_passed", key="abc")
        result = steering_mod.recent_instructions(events_file)
        assert result == ["my instruction"]

    def test_respects_limit(self, events_file):
        for i in range(10):
            steering_mod.record_instruction(events_file, f"instruction {i}")
        result = steering_mod.recent_instructions(events_file, limit=3)
        assert len(result) == 3

    def test_returns_most_recent(self, events_file):
        for i in range(10):
            steering_mod.record_instruction(events_file, f"instruction {i}")
        result = steering_mod.recent_instructions(events_file, limit=3)
        assert "instruction 9" in result
        assert "instruction 7" in result

    def test_returns_empty_on_missing_file(self, tmp_path):
        result = steering_mod.recent_instructions(str(tmp_path / "nope.log"))
        assert result == []

    def test_preserves_instruction_text_exactly(self, events_file):
        steering_mod.record_instruction(events_file, "focus on auth/middleware.py")
        result = steering_mod.recent_instructions(events_file)
        assert result[0] == "focus on auth/middleware.py"


# ── TestInstructionsText ──────────────────────────────────────────────────────

class TestInstructionsText:
    def test_returns_empty_when_no_instructions(self, events_file):
        result = steering_mod.instructions_text(events_file)
        assert result == ""

    def test_returns_formatted_section(self, events_file):
        steering_mod.record_instruction(events_file, "use PostgreSQL")
        result = steering_mod.instructions_text(events_file)
        assert "Operator Instructions" in result
        assert "use PostgreSQL" in result

    def test_highest_priority_label_present(self, events_file):
        steering_mod.record_instruction(events_file, "skip frontend")
        result = steering_mod.instructions_text(events_file)
        assert "highest priority" in result.lower()

    def test_multiple_instructions_all_listed(self, events_file):
        steering_mod.record_instruction(events_file, "first")
        steering_mod.record_instruction(events_file, "second")
        result = steering_mod.instructions_text(events_file)
        assert "first" in result
        assert "second" in result

    def test_respects_limit(self, events_file):
        for i in range(10):
            steering_mod.record_instruction(events_file, f"instruction {i}")
        result = steering_mod.instructions_text(events_file, limit=2)
        assert "instruction 8" in result or "instruction 9" in result
        assert "instruction 0" not in result

    def test_each_instruction_on_own_line(self, events_file):
        steering_mod.record_instruction(events_file, "line one")
        steering_mod.record_instruction(events_file, "line two")
        result = steering_mod.instructions_text(events_file)
        lines = [l for l in result.splitlines() if "- " in l]
        assert len(lines) == 2


# ── TestInstructionCount ──────────────────────────────────────────────────────

class TestInstructionCount:
    def test_zero_when_no_instructions(self, events_file):
        assert steering_mod.instruction_count(events_file) == 0

    def test_counts_only_operator_instructions(self, events_file):
        _write_event(events_file, "task_started", key="abc")
        steering_mod.record_instruction(events_file, "test")
        _write_event(events_file, "task_completed", key="abc")
        assert steering_mod.instruction_count(events_file) == 1

    def test_counts_multiple(self, events_file):
        for _ in range(5):
            steering_mod.record_instruction(events_file, "do something")
        assert steering_mod.instruction_count(events_file) == 5


# ── TestConstants ─────────────────────────────────────────────────────────────

class TestConstants:
    def test_operator_instruction_constant(self):
        assert steering_mod.OPERATOR_INSTRUCTION == "operator_instruction"

    def test_constant_matches_event_type(self, events_file):
        steering_mod.record_instruction(events_file, "test instruction")
        lines = Path(events_file).read_text().splitlines()
        event = json.loads(lines[0])
        assert event["event"] == steering_mod.OPERATOR_INSTRUCTION


# ── TestClearInstructions ─────────────────────────────────────────────────────

class TestClearInstructions:
    def test_clear_emits_event(self, events_file):
        steering_mod.clear_instructions(events_file)
        content = Path(events_file).read_text()
        assert "operator_instructions_cleared" in content

    def test_instructions_still_readable_after_clear(self, events_file):
        steering_mod.record_instruction(events_file, "old instruction")
        steering_mod.clear_instructions(events_file)
        # Instructions are still there (clear doesn't delete)
        result = steering_mod.recent_instructions(events_file)
        assert "old instruction" in result


# ── Integration: planning context injection ───────────────────────────────────

class TestPlanningContextIntegration:
    def test_instructions_injected_into_planning_context(self, tmp_path):
        romyq_dir = tmp_path / ".romyq"
        romyq_dir.mkdir()
        events_path = str(romyq_dir / "events.log")
        Path(events_path).write_text("", encoding="utf-8")
        history_path = str(romyq_dir / "history.json")
        Path(history_path).write_text("[]", encoding="utf-8")
        findings_path = str(romyq_dir / "findings.json")
        Path(findings_path).write_text("[]", encoding="utf-8")

        steering_mod.record_instruction(events_path, "prioritize security")

        from romyq.planning import build_planning_context
        ctx = build_planning_context(
            state={},
            findings_path=findings_path,
            history_path=history_path,
            events_path=events_path,
        )
        assert "prioritize security" in ctx

    def test_no_instructions_empty_section(self, tmp_path):
        romyq_dir = tmp_path / ".romyq"
        romyq_dir.mkdir()
        events_path = str(romyq_dir / "events.log")
        Path(events_path).write_text("", encoding="utf-8")
        history_path = str(romyq_dir / "history.json")
        Path(history_path).write_text("[]", encoding="utf-8")
        findings_path = str(romyq_dir / "findings.json")
        Path(findings_path).write_text("[]", encoding="utf-8")

        from romyq.planning import build_planning_context
        ctx = build_planning_context(
            state={},
            findings_path=findings_path,
            history_path=history_path,
            events_path=events_path,
        )
        assert "Operator Instructions" not in ctx
