"""Tests for romyq.planning_guardrails."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from romyq.planning_guardrails import (
    GuardrailViolation,
    build_guardrail_context,
    validate_and_retry,
    validate_task_against_knowledge,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_knowledge(tmp_path, failures=None, successes=None) -> str:
    """Write a knowledge.json and return its path.

    `failures` is a list of dicts with keys: fingerprint, count, last_reason.
    `successes` is a list of dicts with keys: fingerprint, count.
    Internally, patterns is a flat list where each entry has a `type` field.
    """
    patterns = []
    for f in (failures or []):
        patterns.append({"type": "failure_pattern", **f})
    for s in (successes or []):
        patterns.append({"type": "success_pattern", **s})
    data = {
        "version": 1,
        "generated_at": "2025-01-01T00:00:00+00:00",
        "structure_hash": "abc123",
        "patterns": patterns,
        "lessons": [],
    }
    p = tmp_path / "knowledge.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return str(p)


def _fp(text: str) -> str:
    from romyq.fingerprint import fingerprint
    return fingerprint(text)


# ── TestGuardrailViolation ────────────────────────────────────────────────────

class TestGuardrailViolation:
    def test_is_named_tuple(self):
        v = GuardrailViolation(
            task_preview="run tests",
            reason="failed 5 times",
            fingerprint="abc123",
        )
        assert v.task_preview == "run tests"
        assert v.reason == "failed 5 times"
        assert v.fingerprint == "abc123"

    def test_unpacking(self):
        v = GuardrailViolation("preview", "reason", "fp")
        preview, reason, fp = v
        assert preview == "preview"

    def test_equality(self):
        v1 = GuardrailViolation("t", "r", "f")
        v2 = GuardrailViolation("t", "r", "f")
        assert v1 == v2

    def test_inequality(self):
        v1 = GuardrailViolation("t", "r", "f1")
        v2 = GuardrailViolation("t", "r", "f2")
        assert v1 != v2


# ── TestValidateTaskAgainstKnowledge — basic ──────────────────────────────────

class TestValidateTaskEmpty:
    def test_empty_task_returns_none(self, tmp_path):
        know = _make_knowledge(tmp_path)
        assert validate_task_against_knowledge("", know) is None

    def test_whitespace_task_returns_none(self, tmp_path):
        know = _make_knowledge(tmp_path)
        assert validate_task_against_knowledge("   ", know) is None

    def test_safe_task_returns_none(self, tmp_path):
        know = _make_knowledge(tmp_path)
        assert validate_task_against_knowledge("implement user login", know) is None

    def test_missing_knowledge_file_returns_none(self, tmp_path):
        assert validate_task_against_knowledge(
            "implement login", str(tmp_path / "missing.json")
        ) is None


# ── TestValidateTaskAgainstKnowledge — exact fingerprint match ────────────────

class TestExactFingerprintMatch:
    def test_blocks_task_matching_failure_pattern(self, tmp_path):
        task = "fix the authentication bug in user service"
        fp = _fp(task)
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 5, "last_reason": "import error"}],
        )
        result = validate_task_against_knowledge(task, know, failure_threshold=3)
        assert result is not None
        assert isinstance(result, GuardrailViolation)

    def test_violation_contains_task_preview(self, tmp_path):
        task = "fix the authentication bug in user service"
        fp = _fp(task)
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 5, "last_reason": "import error"}],
        )
        result = validate_task_against_knowledge(task, know, failure_threshold=3)
        assert "fix the authentication bug" in result.task_preview

    def test_violation_contains_reason(self, tmp_path):
        task = "add database migrations"
        fp = _fp(task)
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 4, "last_reason": "syntax error"}],
        )
        result = validate_task_against_knowledge(task, know, failure_threshold=3)
        assert "syntax error" in result.reason

    def test_violation_contains_fingerprint(self, tmp_path):
        task = "add database migrations"
        fp = _fp(task)
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 4, "last_reason": "syntax error"}],
        )
        result = validate_task_against_knowledge(task, know, failure_threshold=3)
        assert result.fingerprint == fp

    def test_below_threshold_not_blocked(self, tmp_path):
        task = "add database migrations"
        fp = _fp(task)
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 2, "last_reason": "syntax error"}],
        )
        # count=2 < threshold=3 → no block
        result = validate_task_against_knowledge(task, know, failure_threshold=3)
        assert result is None

    def test_exactly_at_threshold_is_blocked(self, tmp_path):
        task = "implement password reset"
        fp = _fp(task)
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 3, "last_reason": "test failed"}],
        )
        result = validate_task_against_knowledge(task, know, failure_threshold=3)
        assert result is not None

    def test_different_task_not_blocked(self, tmp_path):
        fp = _fp("implement password reset")
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 10, "last_reason": "test failed"}],
        )
        result = validate_task_against_knowledge("add user profile page", know, failure_threshold=3)
        assert result is None


# ── TestBuildGuardrailContext ─────────────────────────────────────────────────

class TestBuildGuardrailContext:
    def test_returns_string(self):
        v = GuardrailViolation("preview", "failed repeatedly", "fp123")
        result = build_guardrail_context(v)
        assert isinstance(result, str)

    def test_contains_rejection_header(self):
        v = GuardrailViolation("preview", "failed repeatedly", "fp123")
        result = build_guardrail_context(v)
        assert "Guardrail" in result

    def test_contains_task_preview(self):
        v = GuardrailViolation("implement user auth", "failed 5 times", "fp")
        result = build_guardrail_context(v)
        assert "implement user auth" in result

    def test_contains_reason(self):
        v = GuardrailViolation("preview", "mypy error on line 42", "fp")
        result = build_guardrail_context(v)
        assert "mypy error on line 42" in result

    def test_instructs_to_generate_different_task(self):
        v = GuardrailViolation("preview", "reason", "fp")
        result = build_guardrail_context(v)
        assert "DIFFERENT" in result or "different" in result.lower()

    def test_do_not_repeat_instruction(self):
        v = GuardrailViolation("preview", "reason", "fp")
        result = build_guardrail_context(v)
        assert "NOT" in result or "not" in result.lower()


# ── TestValidateAndRetry ──────────────────────────────────────────────────────

class TestValidateAndRetry:
    def test_returns_task_when_no_violation(self, tmp_path):
        know = _make_knowledge(tmp_path)
        task = "implement user login"
        result_task, violation = validate_and_retry(
            lambda extra_context="": "new task",
            task,
            know,
        )
        assert result_task == task
        assert violation is None

    def test_calls_generate_fn_on_violation(self, tmp_path):
        original = "fix the broken auth handler"
        fp = _fp(original)
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 5, "last_reason": "test failed"}],
        )
        calls = []
        def gen_fn(extra_context=""):
            calls.append(extra_context)
            return "completely different task that won't match"
        result_task, violation = validate_and_retry(gen_fn, original, know, failure_threshold=3)
        assert len(calls) >= 1

    def test_returns_last_violation_when_retries_exhausted(self, tmp_path):
        task = "fix broken auth"
        fp = _fp(task)
        alt = "fix broken auth handler again"
        fp2 = _fp(alt)
        know = _make_knowledge(
            tmp_path,
            failures=[
                {"fingerprint": fp, "count": 5, "last_reason": "fail1"},
                {"fingerprint": fp2, "count": 5, "last_reason": "fail2"},
            ],
        )
        def gen_fn(extra_context=""):
            return alt
        result_task, violation = validate_and_retry(
            gen_fn, task, know, failure_threshold=3, max_retries=2
        )
        assert violation is not None

    def test_returns_clean_task_when_retry_passes(self, tmp_path):
        bad_task = "fix broken migration runner"
        fp = _fp(bad_task)
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 5, "last_reason": "fail"}],
        )
        good_task = "implement a completely new feature for user profiles"
        def gen_fn(extra_context=""):
            return good_task
        result_task, violation = validate_and_retry(
            gen_fn, bad_task, know, failure_threshold=3, max_retries=1
        )
        assert result_task == good_task

    def test_generate_fn_exception_handled(self, tmp_path):
        bad = "fix broken thing"
        fp = _fp(bad)
        know = _make_knowledge(
            tmp_path,
            failures=[{"fingerprint": fp, "count": 5, "last_reason": "fail"}],
        )
        def gen_fn(extra_context=""):
            raise RuntimeError("API down")
        result_task, violation = validate_and_retry(gen_fn, bad, know, failure_threshold=3)
        assert result_task == bad  # returns original on exception
        assert violation is not None
