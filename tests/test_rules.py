"""Tests for romyq.rules — project governance rules CRUD."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq import rules as rules_mod


@pytest.fixture()
def rules_file(tmp_path):
    return str(tmp_path / "rules.json")


# ── TestLoad ──────────────────────────────────────────────────────────────────

class TestLoad:
    def test_returns_empty_on_missing_file(self, rules_file):
        data = rules_mod.load(rules_file)
        assert data["rules"] == []
        assert data["version"] == 1

    def test_returns_empty_on_corrupt_json(self, rules_file):
        Path(rules_file).write_text("not json", encoding="utf-8")
        data = rules_mod.load(rules_file)
        assert data["rules"] == []

    def test_loads_existing_rules(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        data = rules_mod.load(rules_file)
        assert len(data["rules"]) == 1

    def test_sets_version_default(self, rules_file):
        Path(rules_file).write_text(json.dumps({"rules": []}), encoding="utf-8")
        data = rules_mod.load(rules_file)
        assert data["version"] == 1

    def test_returns_empty_on_non_dict(self, rules_file):
        Path(rules_file).write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        data = rules_mod.load(rules_file)
        assert data["rules"] == []


# ── TestAddRule ───────────────────────────────────────────────────────────────

class TestAddRule:
    def test_returns_rule_id(self, rules_file):
        rule_id = rules_mod.add_rule(rules_file, "Never use SQLite")
        assert isinstance(rule_id, str)
        assert len(rule_id) == 8

    def test_rule_stored_in_file(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        data = rules_mod.load(rules_file)
        assert len(data["rules"]) == 1
        assert data["rules"][0]["text"] == "Never use SQLite"

    def test_rule_active_by_default(self, rules_file):
        rules_mod.add_rule(rules_file, "Always use PostgreSQL")
        data = rules_mod.load(rules_file)
        assert data["rules"][0]["active"] is True

    def test_default_source_is_manual(self, rules_file):
        rules_mod.add_rule(rules_file, "Backend first")
        data = rules_mod.load(rules_file)
        assert data["rules"][0]["source"] == "manual"

    def test_promoted_source_stored(self, rules_file):
        rules_mod.add_rule(rules_file, "Use PostgreSQL", source="promoted")
        data = rules_mod.load(rules_file)
        assert data["rules"][0]["source"] == "promoted"

    def test_created_at_timestamp_present(self, rules_file):
        rules_mod.add_rule(rules_file, "Require tests")
        data = rules_mod.load(rules_file)
        assert data["rules"][0]["created_at"] != ""

    def test_duplicate_active_rule_not_added(self, rules_file):
        id1 = rules_mod.add_rule(rules_file, "Never use SQLite")
        id2 = rules_mod.add_rule(rules_file, "Never use SQLite")
        assert id1 == id2
        data = rules_mod.load(rules_file)
        assert len(data["rules"]) == 1

    def test_duplicate_case_insensitive(self, rules_file):
        id1 = rules_mod.add_rule(rules_file, "Never use SQLite")
        id2 = rules_mod.add_rule(rules_file, "never use sqlite")
        assert id1 == id2

    def test_multiple_rules_stored(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        rules_mod.add_rule(rules_file, "Always use PostgreSQL")
        data = rules_mod.load(rules_file)
        assert len(data["rules"]) == 2

    def test_empty_text_raises(self, rules_file):
        with pytest.raises(ValueError):
            rules_mod.add_rule(rules_file, "")

    def test_whitespace_only_raises(self, rules_file):
        with pytest.raises(ValueError):
            rules_mod.add_rule(rules_file, "   ")

    def test_strips_whitespace(self, rules_file):
        rules_mod.add_rule(rules_file, "  Backend first  ")
        data = rules_mod.load(rules_file)
        assert data["rules"][0]["text"] == "Backend first"

    def test_invalid_source_defaults_to_manual(self, rules_file):
        rules_mod.add_rule(rules_file, "test rule", source="unknown_source")
        data = rules_mod.load(rules_file)
        assert data["rules"][0]["source"] == "manual"


# ── TestRemoveRule ────────────────────────────────────────────────────────────

class TestRemoveRule:
    def test_deactivates_by_text(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        result = rules_mod.remove_rule(rules_file, "Never use SQLite")
        assert result is True
        active = rules_mod.list_rules(rules_file)
        assert active == []

    def test_deactivates_by_id(self, rules_file):
        rule_id = rules_mod.add_rule(rules_file, "Backend first")
        result = rules_mod.remove_rule(rules_file, rule_id)
        assert result is True
        assert rules_mod.list_rules(rules_file) == []

    def test_returns_false_for_nonexistent(self, rules_file):
        assert rules_mod.remove_rule(rules_file, "nonexistent rule") is False

    def test_does_not_delete_record(self, rules_file):
        rules_mod.add_rule(rules_file, "test rule")
        rules_mod.remove_rule(rules_file, "test rule")
        all_ = rules_mod.all_rules(rules_file)
        assert len(all_) == 1
        assert all_[0]["active"] is False

    def test_case_insensitive_match(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        result = rules_mod.remove_rule(rules_file, "never use sqlite")
        assert result is True

    def test_empty_id_returns_false(self, rules_file):
        assert rules_mod.remove_rule(rules_file, "") is False


# ── TestListRules ─────────────────────────────────────────────────────────────

class TestListRules:
    def test_empty_when_no_rules(self, rules_file):
        assert rules_mod.list_rules(rules_file) == []

    def test_returns_active_rules(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        active = rules_mod.list_rules(rules_file)
        assert len(active) == 1

    def test_excludes_inactive_rules(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        rules_mod.remove_rule(rules_file, "Never use SQLite")
        assert rules_mod.list_rules(rules_file) == []

    def test_multiple_active_rules(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        rules_mod.add_rule(rules_file, "Always use PostgreSQL")
        assert len(rules_mod.list_rules(rules_file)) == 2


# ── TestRulesText ─────────────────────────────────────────────────────────────

class TestRulesText:
    def test_empty_when_no_rules(self, rules_file):
        assert rules_mod.rules_text(rules_file) == ""

    def test_returns_formatted_section(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        text = rules_mod.rules_text(rules_file)
        assert "Project Rules" in text
        assert "Never use SQLite" in text

    def test_all_rules_in_text(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        rules_mod.add_rule(rules_file, "Always use PostgreSQL")
        text = rules_mod.rules_text(rules_file)
        assert "Never use SQLite" in text
        assert "Always use PostgreSQL" in text

    def test_empty_after_all_removed(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        rules_mod.remove_rule(rules_file, "Never use SQLite")
        assert rules_mod.rules_text(rules_file) == ""


# ── TestConstants ─────────────────────────────────────────────────────────────

class TestConstants:
    def test_rule_sources(self):
        assert "manual" in rules_mod.RULE_SOURCES
        assert "promoted" in rules_mod.RULE_SOURCES

    def test_format_rules_empty(self, rules_file):
        text = rules_mod.format_rules(rules_file)
        assert "no rules" in text.lower()

    def test_format_rules_with_content(self, rules_file):
        rules_mod.add_rule(rules_file, "Backend first")
        text = rules_mod.format_rules(rules_file)
        assert "Backend first" in text
