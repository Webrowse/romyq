"""Tests for romyq.timeline — project evolution timeline (capability-level)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq import timeline as tl_mod


@pytest.fixture()
def history_file(tmp_path):
    return str(tmp_path / "history.json")


def _write_history(path: str, entries: list[dict]) -> None:
    Path(path).write_text(json.dumps(entries), encoding="utf-8")


def _entry(task: str, success: bool = True, timestamp: str = "2025-01-15T10:00:00+00:00") -> dict:
    return {
        "task": task,
        "success": success,
        "validation_reason": "ok" if success else "fail",
        "timestamp": timestamp,
        "mode": "impl",
        "commit": "abc123",
    }


# ── TestBuildTimeline ─────────────────────────────────────────────────────────

class TestBuildTimeline:
    def test_returns_list(self, history_file):
        _write_history(history_file, [])
        result = tl_mod.build_timeline(history_file)
        assert isinstance(result, list)

    def test_empty_on_no_history(self, history_file):
        _write_history(history_file, [])
        assert tl_mod.build_timeline(history_file) == []

    def test_empty_on_missing_file(self, tmp_path):
        result = tl_mod.build_timeline(str(tmp_path / "nonexistent.json"))
        assert result == []

    def test_successful_task_appears(self, history_file):
        _write_history(history_file, [_entry("Implement JWT authentication")])
        result = tl_mod.build_timeline(history_file)
        assert len(result) == 1

    def test_failed_task_excluded(self, history_file):
        _write_history(history_file, [_entry("Write tests", success=False)])
        result = tl_mod.build_timeline(history_file)
        assert result == []

    def test_event_has_required_keys(self, history_file):
        _write_history(history_file, [_entry("Write pytest tests")])
        result = tl_mod.build_timeline(history_file)
        ev = result[0]
        assert "timestamp" in ev
        assert "description" in ev
        assert "capability" in ev
        assert "task" in ev

    def test_capability_inferred_for_auth(self, history_file):
        _write_history(history_file, [_entry("Implement JWT authentication and login")])
        result = tl_mod.build_timeline(history_file)
        assert result[0]["capability"] == "Authentication"

    def test_description_is_action_verb_for_known_cap(self, history_file):
        _write_history(history_file, [_entry("Write pytest tests for the user service")])
        result = tl_mod.build_timeline(history_file)
        assert result[0]["description"] == "Added Tests"

    def test_date_extracted_from_timestamp(self, history_file):
        _write_history(history_file, [_entry("Write tests", timestamp="2025-06-15T10:00:00+00:00")])
        result = tl_mod.build_timeline(history_file)
        assert result[0]["timestamp"] == "2025-06-15"

    def test_deduplication_by_capability(self, history_file):
        _write_history(history_file, [
            _entry("Write tests 1"),
            _entry("Write tests 2"),
            _entry("Write tests 3"),
        ])
        result = tl_mod.build_timeline(history_file)
        testing_events = [e for e in result if e["capability"] == "Testing"]
        assert len(testing_events) == 1

    def test_multiple_capabilities_all_appear(self, history_file):
        _write_history(history_file, [
            _entry("Implement JWT authentication"),
            _entry("Write pytest tests"),
        ])
        result = tl_mod.build_timeline(history_file)
        caps = {e["capability"] for e in result}
        assert "Authentication" in caps
        assert "Testing" in caps

    def test_respects_limit(self, history_file):
        entries = []
        caps = ["auth", "test", "database", "deploy", "cache", "security", "docs"]
        for i, kw in enumerate(caps * 4):
            entries.append(_entry(f"Task with {kw} keyword {i}"))
        _write_history(history_file, entries)
        result = tl_mod.build_timeline(history_file, limit=3)
        assert len(result) <= 3

    def test_empty_task_in_entry(self, history_file):
        _write_history(history_file, [_entry("")])
        result = tl_mod.build_timeline(history_file)
        assert isinstance(result, list)


# ── TestActionVerb ─────────────────────────────────────────────────────────────

class TestActionVerb:
    def test_all_known_capabilities_have_verbs(self):
        for cap_name in [
            "Authentication", "Authorization", "Database", "Testing",
            "Validation", "Search", "Documentation", "Security",
            "Observability", "Deployment", "Performance", "Core Features",
        ]:
            verb = tl_mod._action_verb(cap_name)
            assert verb, f"Expected non-empty verb for {cap_name}"

    def test_unknown_returns_empty(self):
        assert tl_mod._action_verb("SomethingUnknown") == ""

    def test_testing_verb(self):
        assert tl_mod._action_verb("Testing") == "Added Tests"

    def test_auth_verb(self):
        assert tl_mod._action_verb("Authentication") == "Added Authentication"

    def test_deployment_verb(self):
        assert "Deploy" in tl_mod._action_verb("Deployment") or "Configured" in tl_mod._action_verb("Deployment")

    def test_database_verb(self):
        verb = tl_mod._action_verb("Database")
        assert "Database" in verb or "Set Up" in verb


# ── TestSummarizeTask ──────────────────────────────────────────────────────────

class TestSummarizeTask:
    def test_returns_first_line(self):
        task = "First line\nSecond line\nThird line"
        result = tl_mod._summarize_task(task)
        assert "First line" in result

    def test_truncates_long_text(self):
        long_task = "a" * 100
        result = tl_mod._summarize_task(long_task, max_len=20)
        assert len(result) <= 22  # 20 + ellipsis char + some buffer

    def test_strips_bullet_prefix(self):
        task = "- Implement user authentication"
        result = tl_mod._summarize_task(task)
        assert not result.startswith("-")

    def test_strips_asterisk_prefix(self):
        task = "* Add test coverage"
        result = tl_mod._summarize_task(task)
        assert not result.startswith("*")

    def test_empty_string(self):
        result = tl_mod._summarize_task("")
        assert isinstance(result, str)

    def test_multiline_blank_first_line(self):
        task = "\n\nActual content"
        result = tl_mod._summarize_task(task)
        assert "Actual content" in result


# ── TestFormatTimeline ─────────────────────────────────────────────────────────

class TestFormatTimeline:
    def test_returns_string(self, history_file):
        _write_history(history_file, [])
        result = tl_mod.format_timeline(history_file)
        assert isinstance(result, str)

    def test_no_history_message(self, history_file):
        _write_history(history_file, [])
        result = tl_mod.format_timeline(history_file)
        assert "no completed work" in result.lower() or "yet" in result.lower()

    def test_contains_description(self, history_file):
        _write_history(history_file, [_entry("Write pytest tests")])
        result = tl_mod.format_timeline(history_file)
        assert "Added Tests" in result or "test" in result.lower()

    def test_contains_date(self, history_file):
        _write_history(history_file, [_entry("Write tests", timestamp="2025-06-15T10:00:00+00:00")])
        result = tl_mod.format_timeline(history_file)
        assert "2025-06-15" in result

    def test_capability_tag_shown(self, history_file):
        _write_history(history_file, [_entry("Write pytest tests")])
        result = tl_mod.format_timeline(history_file)
        assert "[Testing]" in result or "Testing" in result
