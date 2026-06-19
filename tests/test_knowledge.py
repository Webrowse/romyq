"""Tests for romyq.knowledge — knowledge extraction and planning intelligence."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from romyq import knowledge as know_mod


# ── helpers ───────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _write_json(path: str, data) -> None:
    Path(path).write_text(json.dumps(data), encoding="utf-8")


def _make_workspace(tmp_path) -> tuple[str, str, str, str, str]:
    """Return (workspace, know_path, mem_path, hist_path, events_path)."""
    workspace = str(tmp_path)
    romyq_dir = tmp_path / ".romyq"
    romyq_dir.mkdir()
    know_path = str(romyq_dir / "knowledge.json")
    mem_path = str(romyq_dir / "memory.json")
    hist_path = str(romyq_dir / "history.json")
    events_path = str(romyq_dir / "events.log")
    _write_json(hist_path, [])
    _write_json(mem_path, {"entries": [], "missions": {}})
    Path(events_path).write_text("", encoding="utf-8")
    return workspace, know_path, mem_path, hist_path, events_path


def _record_failure(mem_path: str, task: str, reason: str, count: int = 1) -> None:
    from romyq import memory as mem_mod
    for _ in range(count):
        mem_mod.record(
            path=mem_path,
            task=task,
            mission_fp="mfp1",
            outcome="FAILURE",
            evidence=[],
            failure_reason=reason,
            retry_count=1,
        )


def _record_success(mem_path: str, task: str) -> None:
    from romyq import memory as mem_mod
    mem_mod.record(
        path=mem_path,
        task=task,
        mission_fp="mfp1",
        outcome="SUCCESS",
        evidence=[],
        failure_reason="",
        retry_count=0,
    )


def _add_history(hist_path: str, success: bool, reason: str = "") -> None:
    try:
        data = json.loads(Path(hist_path).read_text())
    except Exception:
        data = []
    entry = {
        "task": "some task",
        "mode": "impl",
        "success": success,
        "commit": "",
        "validation_reason": reason,
        "timestamp": _now_iso(),
    }
    data.append(entry)
    _write_json(hist_path, data)


# ── TestKnowledgeLoad ─────────────────────────────────────────────────────────

class TestKnowledgeLoad:
    def test_returns_empty_on_missing_file(self, tmp_path):
        result = know_mod.load(str(tmp_path / "nonexistent.json"))
        assert isinstance(result, dict)
        assert result["version"] == 1
        assert result["patterns"] == []
        assert result["lessons"] == []

    def test_returns_empty_on_corrupt_json(self, tmp_path):
        p = tmp_path / "knowledge.json"
        p.write_text("not json", encoding="utf-8")
        result = know_mod.load(str(p))
        assert result["lessons"] == []

    def test_returns_empty_on_non_dict_json(self, tmp_path):
        p = tmp_path / "knowledge.json"
        p.write_text("[]", encoding="utf-8")
        result = know_mod.load(str(p))
        assert result["lessons"] == []

    def test_loads_valid_knowledge(self, tmp_path):
        p = tmp_path / "knowledge.json"
        data = {"version": 1, "generated_at": "2026-01-01T00:00:00+00:00",
                "structure_hash": "abc", "patterns": [], "lessons": ["do this"]}
        _write_json(str(p), data)
        result = know_mod.load(str(p))
        assert result["lessons"] == ["do this"]
        assert result["structure_hash"] == "abc"

    def test_load_preserves_patterns(self, tmp_path):
        p = tmp_path / "knowledge.json"
        patterns = [{"type": "failure_pattern", "count": 3, "task_preview": "Foo"}]
        data = {"version": 1, "generated_at": "x", "structure_hash": "y",
                "patterns": patterns, "lessons": []}
        _write_json(str(p), data)
        result = know_mod.load(str(p))
        assert len(result["patterns"]) == 1

    def test_load_missing_keys_returns_empty_lists(self, tmp_path):
        p = tmp_path / "knowledge.json"
        _write_json(str(p), {"version": 1})
        result = know_mod.load(str(p))
        assert result.get("patterns", []) == []
        assert result.get("lessons", []) == []


# ── TestStructureHash ─────────────────────────────────────────────────────────

class TestStructureHash:
    def test_deterministic(self):
        h1 = know_mod._structure_hash("ctx", 5, 10)
        h2 = know_mod._structure_hash("ctx", 5, 10)
        assert h1 == h2

    def test_sensitive_to_memory_count(self):
        h1 = know_mod._structure_hash("ctx", 5, 10)
        h2 = know_mod._structure_hash("ctx", 6, 10)
        assert h1 != h2

    def test_sensitive_to_history_count(self):
        h1 = know_mod._structure_hash("ctx", 5, 10)
        h2 = know_mod._structure_hash("ctx", 5, 11)
        assert h1 != h2

    def test_sensitive_to_context_text(self):
        h1 = know_mod._structure_hash("pytest installed", 5, 10)
        h2 = know_mod._structure_hash("mypy installed", 5, 10)
        assert h1 != h2

    def test_returns_16_char_hex(self):
        h = know_mod._structure_hash("ctx", 0, 0)
        assert len(h) == 16
        int(h, 16)  # must be valid hex


# ── TestIsStale ───────────────────────────────────────────────────────────────

class TestIsStale:
    def test_stale_when_knowledge_absent(self, tmp_path):
        _, know_path, mem_path, hist_path, _ = _make_workspace(tmp_path)
        assert know_mod.is_stale(know_path, mem_path, hist_path) is True

    def test_stale_when_generated_at_empty(self, tmp_path):
        _, know_path, mem_path, hist_path, _ = _make_workspace(tmp_path)
        _write_json(know_path, {"version": 1, "generated_at": "",
                                "structure_hash": "abc", "patterns": [], "lessons": []})
        assert know_mod.is_stale(know_path, mem_path, hist_path) is True

    def test_fresh_when_hash_matches(self, tmp_path):
        _, know_path, mem_path, hist_path, _ = _make_workspace(tmp_path)
        ctx = "project context"
        h = know_mod._structure_hash(ctx, 0, 0)
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": h, "patterns": [], "lessons": []})
        assert know_mod.is_stale(know_path, mem_path, hist_path, ctx) is False

    def test_stale_when_memory_count_changes(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        ctx = ""
        h = know_mod._structure_hash(ctx, 0, 0)
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": h, "patterns": [], "lessons": []})
        # Add a memory entry
        _record_failure(mem_path, "some task", "error")
        assert know_mod.is_stale(know_path, mem_path, hist_path, ctx) is True

    def test_stale_when_history_count_changes(self, tmp_path):
        _, know_path, mem_path, hist_path, _ = _make_workspace(tmp_path)
        h = know_mod._structure_hash("", 0, 0)
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": h, "patterns": [], "lessons": []})
        _add_history(hist_path, True)
        assert know_mod.is_stale(know_path, mem_path, hist_path) is True

    def test_stale_when_context_changes(self, tmp_path):
        _, know_path, mem_path, hist_path, _ = _make_workspace(tmp_path)
        h = know_mod._structure_hash("old context", 0, 0)
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": h, "patterns": [], "lessons": []})
        assert know_mod.is_stale(know_path, mem_path, hist_path, "new context") is True

    def test_not_stale_with_empty_files(self, tmp_path):
        _, know_path, mem_path, hist_path, _ = _make_workspace(tmp_path)
        h = know_mod._structure_hash("", 0, 0)
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": h, "patterns": [], "lessons": []})
        assert know_mod.is_stale(know_path, mem_path, hist_path) is False

    def test_count_functions_return_zero_on_missing(self, tmp_path):
        assert know_mod._count_memory_entries(str(tmp_path / "nope.json")) == 0
        assert know_mod._count_history_entries(str(tmp_path / "nope.json")) == 0


# ── TestExtractFailurePatterns ────────────────────────────────────────────────

class TestExtractFailurePatterns:
    def test_returns_empty_for_empty_memory(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        result = know_mod._extract_failure_patterns(mem_path)
        assert result == []

    def test_returns_empty_for_missing_memory(self, tmp_path):
        result = know_mod._extract_failure_patterns(str(tmp_path / "nope.json"))
        assert result == []

    def test_extracts_repeated_failure(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        _record_failure(mem_path, "Add auth module", "ImportError", count=3)
        result = know_mod._extract_failure_patterns(mem_path)
        assert len(result) >= 1
        assert result[0]["type"] == "failure_pattern"
        assert result[0]["count"] >= 3

    def test_filters_single_failure(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        _record_failure(mem_path, "One-time failure task", "network error", count=1)
        result = know_mod._extract_failure_patterns(mem_path)
        # count < 2 should be excluded
        assert all(p["count"] >= 2 for p in result)

    def test_pattern_has_required_keys(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        _record_failure(mem_path, "Add feature X", "timeout", count=2)
        result = know_mod._extract_failure_patterns(mem_path)
        if result:
            p = result[0]
            assert "type" in p
            assert "fingerprint" in p
            assert "task_preview" in p
            assert "count" in p
            assert "last_reason" in p

    def test_last_reason_captured(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        _record_failure(mem_path, "Fix broken test", "AssertionError: expected 1 got 2", count=2)
        result = know_mod._extract_failure_patterns(mem_path)
        if result:
            assert "AssertionError" in result[0]["last_reason"] or result[0]["last_reason"] != ""

    def test_multiple_patterns_sorted_by_count(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        _record_failure(mem_path, "Fix auth bug", "ImportError", count=5)
        _record_failure(mem_path, "Add test coverage", "timeout", count=2)
        result = know_mod._extract_failure_patterns(mem_path)
        counts = [p["count"] for p in result]
        assert counts == sorted(counts, reverse=True)


# ── TestExtractSuccessPatterns ────────────────────────────────────────────────

class TestExtractSuccessPatterns:
    def test_returns_empty_for_empty_memory(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        result = know_mod._extract_success_patterns(mem_path)
        assert result == []

    def test_returns_empty_for_missing_memory(self, tmp_path):
        result = know_mod._extract_success_patterns(str(tmp_path / "nope.json"))
        assert result == []

    def test_extracts_success_pattern(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        _record_success(mem_path, "Add unit tests for auth module")
        _record_success(mem_path, "Add unit tests for auth module")
        result = know_mod._extract_success_patterns(mem_path)
        assert len(result) >= 1
        assert result[0]["type"] == "success_pattern"

    def test_ignores_failure_entries(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        _record_failure(mem_path, "Failed task", "error", count=3)
        result = know_mod._extract_success_patterns(mem_path)
        assert result == []

    def test_pattern_has_required_keys(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        _record_success(mem_path, "Implement login endpoint")
        _record_success(mem_path, "Implement login endpoint")
        result = know_mod._extract_success_patterns(mem_path)
        if result:
            p = result[0]
            assert "type" in p
            assert "fingerprint" in p
            assert "task_preview" in p
            assert "count" in p

    def test_mixed_entries(self, tmp_path):
        _, _, mem_path, _, _ = _make_workspace(tmp_path)
        _record_success(mem_path, "Add passing test")
        _record_failure(mem_path, "Add passing test", "error", count=1)
        result = know_mod._extract_success_patterns(mem_path)
        # At least one success pattern should appear
        assert len(result) >= 1


# ── TestSynthesizeLessons ─────────────────────────────────────────────────────

class TestSynthesizeLessons:
    def test_empty_with_no_data(self, tmp_path):
        _, _, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        result = know_mod._synthesize_lessons([], hist_path, events_path, "", mem_path)
        assert isinstance(result, list)

    def test_lesson_from_failure_pattern(self, tmp_path):
        _, _, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        patterns = [{"type": "failure_pattern", "task_preview": "Add auth module",
                     "count": 3, "last_reason": "ImportError"}]
        lessons = know_mod._synthesize_lessons(patterns, hist_path, events_path, "", mem_path)
        assert any("auth module" in l or "Add auth module" in l for l in lessons)

    def test_lesson_count_in_failure_mention(self, tmp_path):
        _, _, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        patterns = [{"type": "failure_pattern", "task_preview": "Foo bar task",
                     "count": 5, "last_reason": "timeout"}]
        lessons = know_mod._synthesize_lessons(patterns, hist_path, events_path, "", mem_path)
        assert any("5" in l for l in lessons)

    def test_rate_limit_lesson_emitted(self, tmp_path):
        _, _, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        for _ in range(3):
            Path(events_path).open("a").write(
                '{"ts":"2026-01-01T00:00:00+00:00","event":"rate_limit_detected"}\n'
            )
        patterns = []
        lessons = know_mod._synthesize_lessons(patterns, hist_path, events_path, "", mem_path)
        assert any("rate limit" in l.lower() or "Rate limit" in l for l in lessons)

    def test_context_mypy_lesson(self, tmp_path):
        _, _, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        ctx = "mypy is configured for type checking"
        lessons = know_mod._synthesize_lessons([], hist_path, events_path, ctx, mem_path)
        assert any("type check" in l.lower() for l in lessons)

    def test_context_pytest_lesson(self, tmp_path):
        _, _, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        ctx = "pytest is the test framework"
        lessons = know_mod._synthesize_lessons([], hist_path, events_path, ctx, mem_path)
        assert any("test" in l.lower() for l in lessons)

    def test_context_ruff_lesson(self, tmp_path):
        _, _, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        ctx = "ruff linter is configured"
        lessons = know_mod._synthesize_lessons([], hist_path, events_path, ctx, mem_path)
        assert any("linter" in l.lower() or "linting" in l.lower() for l in lessons)

    def test_context_precommit_lesson(self, tmp_path):
        _, _, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        ctx = "pre-commit hooks are installed"
        lessons = know_mod._synthesize_lessons([], hist_path, events_path, ctx, mem_path)
        assert any("pre-commit" in l.lower() or "hook" in l.lower() for l in lessons)


# ── TestGenerate ──────────────────────────────────────────────────────────────

class TestGenerate:
    def test_returns_dict_with_required_keys(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        result = know_mod.generate(know_path, mem_path, hist_path, events_path)
        assert "version" in result
        assert "generated_at" in result
        assert "structure_hash" in result
        assert "patterns" in result
        assert "lessons" in result

    def test_version_is_1(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        result = know_mod.generate(know_path, mem_path, hist_path, events_path)
        assert result["version"] == 1

    def test_generated_at_is_iso_timestamp(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        result = know_mod.generate(know_path, mem_path, hist_path, events_path)
        dt = datetime.fromisoformat(result["generated_at"])
        assert dt is not None

    def test_structure_hash_is_16_chars(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        result = know_mod.generate(know_path, mem_path, hist_path, events_path)
        assert len(result["structure_hash"]) == 16

    def test_patterns_is_list(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        result = know_mod.generate(know_path, mem_path, hist_path, events_path)
        assert isinstance(result["patterns"], list)

    def test_includes_failure_patterns_when_present(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        _record_failure(mem_path, "Add authentication service", "ModuleNotFoundError", count=3)
        result = know_mod.generate(know_path, mem_path, hist_path, events_path)
        fp_patterns = [p for p in result["patterns"] if p["type"] == "failure_pattern"]
        assert len(fp_patterns) >= 1

    def test_lessons_list_is_strings(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        result = know_mod.generate(know_path, mem_path, hist_path, events_path, "pytest configured")
        assert all(isinstance(l, str) for l in result["lessons"])


# ── TestWrite ─────────────────────────────────────────────────────────────────

class TestWrite:
    def test_creates_file(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        know_mod.write(know_path, mem_path, hist_path, events_path)
        assert Path(know_path).exists()

    def test_file_is_valid_json(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        know_mod.write(know_path, mem_path, hist_path, events_path)
        data = json.loads(Path(know_path).read_text())
        assert isinstance(data, dict)

    def test_returns_path(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        result = know_mod.write(know_path, mem_path, hist_path, events_path)
        assert result == know_path

    def test_overwrites_stale_knowledge(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        old = {"version": 1, "generated_at": "2020-01-01T00:00:00+00:00",
               "structure_hash": "old", "patterns": [], "lessons": ["old lesson"]}
        _write_json(know_path, old)
        know_mod.write(know_path, mem_path, hist_path, events_path)
        new_data = json.loads(Path(know_path).read_text())
        assert new_data.get("structure_hash") != "old"

    def test_atomic_write_no_tmp_left(self, tmp_path):
        _, know_path, mem_path, hist_path, events_path = _make_workspace(tmp_path)
        know_mod.write(know_path, mem_path, hist_path, events_path)
        tmp_files = list(Path(tmp_path / ".romyq").glob("*.tmp"))
        assert tmp_files == []


# ── TestLessonsText ───────────────────────────────────────────────────────────

class TestLessonsText:
    def test_returns_empty_when_no_knowledge(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        result = know_mod.lessons_text(know_path)
        assert result == ""

    def test_returns_empty_when_lessons_list_empty(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": [], "lessons": []})
        result = know_mod.lessons_text(know_path)
        assert result == ""

    def test_returns_formatted_string(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": [],
                                "lessons": ["Lesson one", "Lesson two"]})
        result = know_mod.lessons_text(know_path)
        assert "Lesson one" in result
        assert "Lesson two" in result

    def test_includes_count_in_header(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": [],
                                "lessons": ["A", "B", "C"]})
        result = know_mod.lessons_text(know_path)
        assert "3" in result

    def test_respects_limit(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        lessons = [f"Lesson {i}" for i in range(20)]
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": [], "lessons": lessons})
        result = know_mod.lessons_text(know_path, limit=3)
        assert "Lesson 0" in result
        assert "Lesson 19" not in result

    def test_numbered_list(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": [],
                                "lessons": ["Do this", "Do that"]})
        result = know_mod.lessons_text(know_path)
        assert "1." in result
        assert "2." in result


# ── TestTopPatterns ───────────────────────────────────────────────────────────

class TestTopPatterns:
    def test_failure_patterns_sorted_by_count(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        patterns = [
            {"type": "failure_pattern", "fingerprint": "a", "task_preview": "Task A",
             "count": 2, "last_reason": ""},
            {"type": "failure_pattern", "fingerprint": "b", "task_preview": "Task B",
             "count": 5, "last_reason": ""},
        ]
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": patterns, "lessons": []})
        result = know_mod.top_failure_patterns(know_path)
        assert result[0]["count"] == 5
        assert result[1]["count"] == 2

    def test_success_patterns_sorted_by_count(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        patterns = [
            {"type": "success_pattern", "fingerprint": "a", "task_preview": "Task A", "count": 1},
            {"type": "success_pattern", "fingerprint": "b", "task_preview": "Task B", "count": 7},
        ]
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": patterns, "lessons": []})
        result = know_mod.top_success_patterns(know_path)
        assert result[0]["count"] == 7

    def test_failure_patterns_excludes_successes(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        patterns = [
            {"type": "success_pattern", "fingerprint": "a", "task_preview": "OK", "count": 9},
            {"type": "failure_pattern", "fingerprint": "b", "task_preview": "Fail", "count": 2,
             "last_reason": ""},
        ]
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": patterns, "lessons": []})
        result = know_mod.top_failure_patterns(know_path)
        assert all(p["type"] == "failure_pattern" for p in result)

    def test_success_patterns_excludes_failures(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        patterns = [
            {"type": "failure_pattern", "fingerprint": "a", "task_preview": "Fail", "count": 9,
             "last_reason": ""},
            {"type": "success_pattern", "fingerprint": "b", "task_preview": "OK", "count": 2},
        ]
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": patterns, "lessons": []})
        result = know_mod.top_success_patterns(know_path)
        assert all(p["type"] == "success_pattern" for p in result)

    def test_respects_limit(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        patterns = [
            {"type": "failure_pattern", "fingerprint": f"fp{i}",
             "task_preview": f"Task {i}", "count": i, "last_reason": ""}
            for i in range(20)
        ]
        _write_json(know_path, {"version": 1, "generated_at": _now_iso(),
                                "structure_hash": "x", "patterns": patterns, "lessons": []})
        result = know_mod.top_failure_patterns(know_path, limit=3)
        assert len(result) == 3

    def test_returns_empty_for_missing_knowledge(self, tmp_path):
        _, know_path, _, _, _ = _make_workspace(tmp_path)
        result = know_mod.top_failure_patterns(know_path)
        assert result == []
        result2 = know_mod.top_success_patterns(know_path)
        assert result2 == []
