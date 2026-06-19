"""Tests for romyq.decisions — governance decision log."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq import decisions as dec_mod


@pytest.fixture()
def decisions_file(tmp_path):
    return str(tmp_path / "decisions.json")


# ── TestLoad ──────────────────────────────────────────────────────────────────

class TestLoad:
    def test_returns_empty_list_on_missing_file(self, decisions_file):
        assert dec_mod.load(decisions_file) == []

    def test_returns_empty_list_on_corrupt_json(self, decisions_file):
        Path(decisions_file).write_text("not json", encoding="utf-8")
        assert dec_mod.load(decisions_file) == []

    def test_returns_empty_on_non_list(self, decisions_file):
        Path(decisions_file).write_text(json.dumps({"key": "val"}), encoding="utf-8")
        assert dec_mod.load(decisions_file) == []

    def test_loads_existing_decisions(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "test rule")
        entries = dec_mod.load(decisions_file)
        assert len(entries) == 1


# ── TestRecord ────────────────────────────────────────────────────────────────

class TestRecord:
    def test_returns_non_empty_id(self, decisions_file):
        id_ = dec_mod.record(decisions_file, "rule_added", "Never use SQLite")
        assert isinstance(id_, str)
        assert len(id_) == 8

    def test_stores_type(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "test")
        entries = dec_mod.load(decisions_file)
        assert entries[0]["type"] == "rule_added"

    def test_stores_detail(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "Never use SQLite")
        entries = dec_mod.load(decisions_file)
        assert "Never use SQLite" in entries[0]["detail"]

    def test_stores_timestamp(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "test")
        entries = dec_mod.load(decisions_file)
        assert entries[0]["timestamp"] != ""

    def test_stores_id(self, decisions_file):
        id_ = dec_mod.record(decisions_file, "rule_added", "test")
        entries = dec_mod.load(decisions_file)
        assert entries[0]["id"] == id_

    def test_unknown_type_stored_as_planner_override(self, decisions_file):
        dec_mod.record(decisions_file, "unknown_type", "test")
        entries = dec_mod.load(decisions_file)
        assert entries[0]["type"] == "planner_override"

    def test_context_kwargs_stored(self, decisions_file):
        dec_mod.record(decisions_file, "task_rejected", "detail", rule_id="abc123", task="something")
        entries = dec_mod.load(decisions_file)
        ctx = entries[0].get("context", {})
        assert ctx.get("rule_id") == "abc123"
        assert ctx.get("task") == "something"

    def test_multiple_records_appended(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "rule 1")
        dec_mod.record(decisions_file, "rule_removed", "rule 2")
        entries = dec_mod.load(decisions_file)
        assert len(entries) == 2

    def test_truncates_long_detail(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "x" * 400)
        entries = dec_mod.load(decisions_file)
        assert len(entries[0]["detail"]) <= 300

    def test_never_raises(self, tmp_path):
        # Even with an invalid path, record() should not raise
        result = dec_mod.record("/invalid/path/decisions.json", "rule_added", "test")
        assert result == ""  # returns empty string on error


# ── TestRecent ────────────────────────────────────────────────────────────────

class TestRecent:
    def test_empty_when_no_decisions(self, decisions_file):
        assert dec_mod.recent(decisions_file) == []

    def test_returns_newest_first(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "first")
        dec_mod.record(decisions_file, "rule_removed", "second")
        entries = dec_mod.recent(decisions_file)
        assert entries[0]["detail"] == "second"
        assert entries[1]["detail"] == "first"

    def test_respects_limit(self, decisions_file):
        for i in range(10):
            dec_mod.record(decisions_file, "rule_added", f"rule {i}")
        entries = dec_mod.recent(decisions_file, limit=3)
        assert len(entries) == 3

    def test_most_recent_within_limit(self, decisions_file):
        for i in range(10):
            dec_mod.record(decisions_file, "rule_added", f"rule {i}")
        entries = dec_mod.recent(decisions_file, limit=3)
        assert entries[0]["detail"] == "rule 9"


# ── TestCount ─────────────────────────────────────────────────────────────────

class TestCount:
    def test_zero_on_empty(self, decisions_file):
        assert dec_mod.count(decisions_file) == 0

    def test_counts_all_entries(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "a")
        dec_mod.record(decisions_file, "rule_removed", "b")
        assert dec_mod.count(decisions_file) == 2


# ── TestCountByType ───────────────────────────────────────────────────────────

class TestCountByType:
    def test_empty_dict_on_no_decisions(self, decisions_file):
        assert dec_mod.count_by_type(decisions_file) == {}

    def test_counts_each_type(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "a")
        dec_mod.record(decisions_file, "rule_added", "b")
        dec_mod.record(decisions_file, "task_rejected", "c")
        by_type = dec_mod.count_by_type(decisions_file)
        assert by_type["rule_added"] == 2
        assert by_type["task_rejected"] == 1


# ── TestFormatDecisions ───────────────────────────────────────────────────────

class TestFormatDecisions:
    def test_empty_message_on_no_decisions(self, decisions_file):
        text = dec_mod.format_decisions(decisions_file)
        assert "no decisions" in text.lower()

    def test_contains_type(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "Never use SQLite")
        text = dec_mod.format_decisions(decisions_file)
        assert "rule_added" in text

    def test_contains_detail(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "Never use SQLite")
        text = dec_mod.format_decisions(decisions_file)
        assert "Never use SQLite" in text

    def test_contains_timestamp(self, decisions_file):
        dec_mod.record(decisions_file, "rule_added", "test")
        text = dec_mod.format_decisions(decisions_file)
        assert "20" in text  # year prefix


# ── TestDecisionTypes ─────────────────────────────────────────────────────────

class TestDecisionTypes:
    def test_all_expected_types_present(self):
        expected = {
            "rule_added", "rule_removed", "task_rejected",
            "planner_override", "operator_intervention",
            "plan_repaired", "rule_triggered",
        }
        assert expected.issubset(dec_mod.DECISION_TYPES)

    def test_rule_triggered_stored(self, decisions_file):
        dec_mod.record(decisions_file, "rule_triggered", "Never use SQLite violated")
        entries = dec_mod.load(decisions_file)
        assert entries[0]["type"] == "rule_triggered"

    def test_plan_repaired_stored(self, decisions_file):
        dec_mod.record(decisions_file, "plan_repaired", "3 tasks replaced")
        entries = dec_mod.load(decisions_file)
        assert entries[0]["type"] == "plan_repaired"
