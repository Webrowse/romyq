"""Tests for romyq.rule_guardrails — rule-based task validation."""
from __future__ import annotations

import pytest

from romyq import rules as rules_mod
from romyq.rule_guardrails import (
    RuleViolation,
    _extract_blocker_term,
    build_rule_violation_context,
    check_task_against_rules,
    relevant_rules,
)


@pytest.fixture()
def rules_file(tmp_path):
    return str(tmp_path / "rules.json")


# ── TestExtractBlockerTerm ────────────────────────────────────────────────────

class TestExtractBlockerTerm:
    def test_never_use(self):
        assert _extract_blocker_term("Never use SQLite") == "sqlite"

    def test_avoid_using(self):
        assert _extract_blocker_term("Avoid using Redis") == "redis"

    def test_do_not_use(self):
        assert _extract_blocker_term("Do not use MongoDB") == "mongodb"

    def test_never_short(self):
        assert _extract_blocker_term("Never touch frontend") == "touch frontend"

    def test_avoid_short(self):
        assert _extract_blocker_term("Avoid global variables") == "global variables"

    def test_advisory_rule_returns_none(self):
        assert _extract_blocker_term("Always use PostgreSQL") is None

    def test_prefer_rule_returns_none(self):
        assert _extract_blocker_term("Prefer Rust") is None

    def test_backend_first_returns_none(self):
        assert _extract_blocker_term("Backend first") is None

    def test_require_tests_returns_none(self):
        assert _extract_blocker_term("Require tests") is None

    def test_case_insensitive(self):
        assert _extract_blocker_term("NEVER USE REDIS") == "redis"


# ── TestRuleViolation ─────────────────────────────────────────────────────────

class TestRuleViolation:
    def test_is_named_tuple(self):
        v = RuleViolation(
            task_preview="add sqlite database",
            violated_rule="Never use SQLite",
            rule_id="abc12345",
        )
        assert v.task_preview == "add sqlite database"
        assert v.violated_rule == "Never use SQLite"
        assert v.rule_id == "abc12345"


# ── TestCheckTaskAgainstRules ─────────────────────────────────────────────────

class TestCheckTaskAgainstRules:
    def test_no_rules_returns_none(self, rules_file):
        result = check_task_against_rules("add sqlite database", rules_file)
        assert result is None

    def test_blocking_rule_triggered(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        result = check_task_against_rules("add sqlite database", rules_file)
        assert result is not None
        assert isinstance(result, RuleViolation)

    def test_violation_contains_rule_text(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        result = check_task_against_rules("create sqlite schema", rules_file)
        assert "Never use SQLite" in result.violated_rule

    def test_violation_contains_task_preview(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        result = check_task_against_rules("create sqlite schema and migrations", rules_file)
        assert "sqlite" in result.task_preview.lower()

    def test_violation_contains_rule_id(self, rules_file):
        rule_id = rules_mod.add_rule(rules_file, "Never use SQLite")
        result = check_task_against_rules("use sqlite for storage", rules_file)
        assert result.rule_id == rule_id

    def test_advisory_rule_not_blocking(self, rules_file):
        rules_mod.add_rule(rules_file, "Always use PostgreSQL")
        result = check_task_against_rules("create a database schema", rules_file)
        assert result is None

    def test_empty_task_returns_none(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        assert check_task_against_rules("", rules_file) is None

    def test_whitespace_task_returns_none(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        assert check_task_against_rules("   ", rules_file) is None

    def test_case_insensitive_task_matching(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        result = check_task_against_rules("Add SQLITE database", rules_file)
        assert result is not None

    def test_inactive_rule_not_blocking(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        rules_mod.remove_rule(rules_file, "Never use SQLite")
        result = check_task_against_rules("add sqlite database", rules_file)
        assert result is None

    def test_compliant_task_returns_none(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        result = check_task_against_rules("implement PostgreSQL migrations", rules_file)
        assert result is None

    def test_avoid_prefix_blocking(self, rules_file):
        rules_mod.add_rule(rules_file, "Avoid using Redis")
        result = check_task_against_rules("add Redis caching layer", rules_file)
        assert result is not None

    def test_multiple_rules_first_match_returned(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        rules_mod.add_rule(rules_file, "Avoid using Redis")
        result = check_task_against_rules("add sqlite with redis cache", rules_file)
        assert result is not None


# ── TestBuildRuleViolationContext ─────────────────────────────────────────────

class TestBuildRuleViolationContext:
    def test_returns_string(self):
        v = RuleViolation("task preview", "Never use SQLite", "abc12345")
        result = build_rule_violation_context(v)
        assert isinstance(result, str)

    def test_contains_rule_violation_header(self):
        v = RuleViolation("task preview", "Never use SQLite", "abc12345")
        result = build_rule_violation_context(v)
        assert "Rule Violation" in result

    def test_contains_task_preview(self):
        v = RuleViolation("add sqlite database", "Never use SQLite", "abc12345")
        result = build_rule_violation_context(v)
        assert "add sqlite database" in result

    def test_contains_violated_rule(self):
        v = RuleViolation("task preview", "Never use SQLite", "abc12345")
        result = build_rule_violation_context(v)
        assert "Never use SQLite" in result

    def test_instructs_different_task(self):
        v = RuleViolation("task preview", "Never use SQLite", "abc12345")
        result = build_rule_violation_context(v)
        assert "DIFFERENT" in result or "different" in result.lower()


# ── TestRelevantRules ─────────────────────────────────────────────────────────

class TestRelevantRules:
    def test_empty_when_no_rules(self, rules_file):
        result = relevant_rules("add postgresql database", rules_file)
        assert result == []

    def test_returns_relevant_rules(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        result = relevant_rules("add sqlite schema", rules_file)
        assert "Never use SQLite" in result

    def test_excludes_unrelated_rules(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use Redis")
        result = relevant_rules("add postgresql migrations", rules_file)
        assert result == []

    def test_empty_task_returns_empty(self, rules_file):
        rules_mod.add_rule(rules_file, "Never use SQLite")
        assert relevant_rules("", rules_file) == []
