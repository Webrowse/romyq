"""Tests for romyq.memory — execution memory persistence and query API."""
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from romyq.memory import (
    MemoryEntry,
    _empty,
    all_missions,
    avg_attempts_per_task,
    entries_for,
    entries_similar_to,
    failure_count,
    load,
    mission_summary,
    most_failed,
    overall_success_rate,
    prior_outcomes_text,
    recent_failures,
    recent_fingerprints,
    record,
    retry_rate,
    update_mission,
)


# ── helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def mem_path(tmp_path):
    return str(tmp_path / "memory.json")


def _rec(mem_path, task="Add health endpoint", mission_fp="mfp1",
         outcome="SUCCESS", failure_reason="", retry_count=0, evidence=None):
    return record(
        path=mem_path,
        task=task,
        mission_fp=mission_fp,
        outcome=outcome,
        evidence=evidence or [],
        failure_reason=failure_reason,
        retry_count=retry_count,
    )


# ── load() ────────────────────────────────────────────────────────────────────

class TestLoad:
    def test_returns_empty_when_absent(self, mem_path):
        data = load(mem_path)
        assert data == _empty()

    def test_returns_empty_on_corrupt_file(self, mem_path):
        Path(mem_path).write_text("not json", encoding="utf-8")
        data = load(mem_path)
        assert data["entries"] == []

    def test_round_trips(self, mem_path):
        _rec(mem_path)
        data = load(mem_path)
        assert len(data["entries"]) == 1

    def test_adds_missing_keys_on_partial_data(self, mem_path):
        # Write a file with only 'entries' — load should add 'missions'
        Path(mem_path).write_text(json.dumps({"version": 1, "entries": []}), encoding="utf-8")
        data = load(mem_path)
        assert "missions" in data


# ── record() ──────────────────────────────────────────────────────────────────

class TestRecord:
    def test_creates_file_on_first_call(self, mem_path):
        _rec(mem_path)
        assert Path(mem_path).exists()

    def test_entry_has_expected_fields(self, mem_path):
        e = _rec(mem_path, task="Add endpoint", mission_fp="mfp1",
                 outcome="FAILURE", failure_reason="route not found")
        assert e["fp"] == pytest.approx(e["fp"])  # just check it's set
        assert e["task"] == "Add endpoint"
        assert e["out"] == "FAILURE"
        assert e["why"] == "route not found"
        assert e["mfp"] == "mfp1"
        assert isinstance(e["ts"], str)

    def test_entry_done_true_for_success(self, mem_path):
        e = _rec(mem_path, outcome="SUCCESS")
        assert e["done"] is True

    def test_entry_done_false_for_failure(self, mem_path):
        e = _rec(mem_path, outcome="FAILURE")
        assert e["done"] is False

    def test_entry_done_true_for_no_action(self, mem_path):
        e = _rec(mem_path, outcome="NO_ACTION_REQUIRED")
        assert e["done"] is True

    def test_multiple_records_accumulate(self, mem_path):
        for i in range(5):
            _rec(mem_path, task=f"task {i}")
        data = load(mem_path)
        assert len(data["entries"]) == 5

    def test_atomic_write(self, mem_path):
        # After record(), the file must be valid JSON
        _rec(mem_path)
        data = json.loads(Path(mem_path).read_text(encoding="utf-8"))
        assert "entries" in data

    def test_task_text_capped_at_400_chars(self, mem_path):
        long_task = "x" * 600
        e = _rec(mem_path, task=long_task)
        assert len(e["task"]) <= 400

    def test_evidence_capped_at_5_lines(self, mem_path):
        evidence = [f"line {i}" for i in range(10)]
        e = _rec(mem_path, evidence=evidence)
        assert len(e["ev"]) <= 5

    def test_failure_reason_capped_at_300_chars(self, mem_path):
        long_reason = "r" * 500
        e = _rec(mem_path, outcome="FAILURE", failure_reason=long_reason)
        assert len(e["why"]) <= 300

    def test_bounded_growth(self, mem_path, monkeypatch):
        monkeypatch.setenv("ROMYQ_MAX_MEMORY", "5")
        for i in range(10):
            _rec(mem_path, task=f"task {i}")
        data = load(mem_path)
        assert len(data["entries"]) <= 5

    def test_oldest_pruned_when_at_cap(self, mem_path, monkeypatch):
        monkeypatch.setenv("ROMYQ_MAX_MEMORY", "3")
        for i in range(5):
            _rec(mem_path, task=f"task {i}")
        data = load(mem_path)
        tasks = [e["task"] for e in data["entries"]]
        # Oldest (task 0, task 1) should be pruned
        assert "task 0" not in tasks
        assert "task 4" in tasks

    def test_fingerprint_stored(self, mem_path):
        e = _rec(mem_path, task="Add health endpoint")
        assert len(e["fp"]) == 12
        assert all(c in "0123456789abcdef" for c in e["fp"])


# ── entries_for() ─────────────────────────────────────────────────────────────

class TestEntriesFor:
    def test_returns_matching_entries(self, mem_path):
        _rec(mem_path, task="Add health endpoint")
        _rec(mem_path, task="Fix bug in parser")
        from romyq.fingerprint import fingerprint as fp
        target = fp("Add health endpoint")
        results = entries_for(mem_path, target)
        assert len(results) == 1
        assert results[0]["task"] == "Add health endpoint"

    def test_returns_empty_for_unknown_fp(self, mem_path):
        _rec(mem_path, task="some task")
        assert entries_for(mem_path, "doesnotexist") == []

    def test_returns_multiple_for_same_task(self, mem_path):
        for _ in range(3):
            _rec(mem_path, task="Add health endpoint", outcome="FAILURE")
        from romyq.fingerprint import fingerprint as fp
        target = fp("Add health endpoint")
        results = entries_for(mem_path, target)
        assert len(results) == 3


# ── entries_similar_to() ──────────────────────────────────────────────────────

class TestEntriesSimilarTo:
    def test_finds_exact_match(self, mem_path):
        _rec(mem_path, task="Add health endpoint")
        results = entries_similar_to(mem_path, "Add health endpoint")
        assert len(results) >= 1

    def test_finds_similar_tasks(self, mem_path):
        _rec(mem_path, task="add health endpoint to the api server")
        # Highly similar text
        results = entries_similar_to(mem_path, "add health endpoint api", threshold=0.3)
        assert len(results) >= 1

    def test_no_false_positives_for_unrelated_tasks(self, mem_path):
        _rec(mem_path, task="refactor css stylesheet layout")
        results = entries_similar_to(mem_path, "implement database migration", threshold=0.4)
        assert len(results) == 0

    def test_empty_memory_returns_empty(self, mem_path):
        assert entries_similar_to(mem_path, "any task") == []


# ── recent_failures() ─────────────────────────────────────────────────────────

class TestRecentFailures:
    def test_returns_only_failures(self, mem_path):
        _rec(mem_path, task="task a", outcome="SUCCESS")
        _rec(mem_path, task="task b", outcome="FAILURE", failure_reason="crash")
        failures = recent_failures(mem_path)
        assert len(failures) == 1
        assert failures[0]["out"] == "FAILURE"

    def test_respects_limit(self, mem_path):
        for i in range(15):
            _rec(mem_path, task=f"task {i}", outcome="FAILURE")
        failures = recent_failures(mem_path, limit=5)
        assert len(failures) == 5

    def test_empty_when_no_failures(self, mem_path):
        _rec(mem_path, outcome="SUCCESS")
        assert recent_failures(mem_path) == []

    def test_empty_memory_returns_empty(self, mem_path):
        assert recent_failures(mem_path) == []


# ── most_failed() ─────────────────────────────────────────────────────────────

class TestMostFailed:
    def test_ranks_by_failure_count(self, mem_path):
        for _ in range(3):
            _rec(mem_path, task="task alpha", outcome="FAILURE", failure_reason="r1")
        for _ in range(1):
            _rec(mem_path, task="task beta", outcome="FAILURE", failure_reason="r2")
        results = most_failed(mem_path)
        assert results[0][1] == 3  # highest count first
        assert results[1][1] == 1

    def test_returns_4_tuple(self, mem_path):
        _rec(mem_path, task="task alpha", outcome="FAILURE", failure_reason="reason")
        result = most_failed(mem_path)
        fp, cnt, preview, last_reason = result[0]
        assert isinstance(fp, str)
        assert cnt == 1
        assert "task alpha" in preview
        assert "reason" in last_reason

    def test_empty_when_no_failures(self, mem_path):
        _rec(mem_path, outcome="SUCCESS")
        assert most_failed(mem_path) == []

    def test_respects_limit(self, mem_path):
        for i in range(15):
            _rec(mem_path, task=f"unique task {i}", outcome="FAILURE")
        results = most_failed(mem_path, limit=5)
        assert len(results) <= 5


# ── prior_outcomes_text() ─────────────────────────────────────────────────────

class TestPriorOutcomesText:
    def test_returns_empty_when_no_prior(self, mem_path):
        assert prior_outcomes_text(mem_path, "brand new task xyz") == ""

    def test_mentions_failure_count(self, mem_path):
        for _ in range(3):
            _rec(mem_path, task="Add health endpoint", outcome="FAILURE",
                 failure_reason="route not found")
        text = prior_outcomes_text(mem_path, "Add health endpoint")
        assert "3" in text or "failed" in text.lower()

    def test_includes_failure_reason(self, mem_path):
        _rec(mem_path, task="Add health endpoint", outcome="FAILURE",
             failure_reason="route not found in router")
        text = prior_outcomes_text(mem_path, "Add health endpoint")
        assert "route not found" in text

    def test_includes_do_not_repeat_guidance(self, mem_path):
        _rec(mem_path, task="Add health endpoint", outcome="FAILURE")
        text = prior_outcomes_text(mem_path, "Add health endpoint")
        assert "not" in text.lower() and "repeat" in text.lower()

    def test_returns_string(self, mem_path):
        _rec(mem_path, task="task", outcome="FAILURE")
        result = prior_outcomes_text(mem_path, "task")
        assert isinstance(result, str)

    def test_mentions_successes_too(self, mem_path):
        _rec(mem_path, task="Add health endpoint", outcome="SUCCESS")
        text = prior_outcomes_text(mem_path, "Add health endpoint")
        assert "succeeded" in text.lower() or "success" in text.lower()


# ── overall_success_rate() ────────────────────────────────────────────────────

class TestOverallSuccessRate:
    def test_returns_negative_when_empty(self, mem_path):
        assert overall_success_rate(mem_path) == -1.0

    def test_all_success(self, mem_path):
        _rec(mem_path, outcome="SUCCESS")
        _rec(mem_path, outcome="SUCCESS")
        assert overall_success_rate(mem_path) == 1.0

    def test_all_failure(self, mem_path):
        _rec(mem_path, outcome="FAILURE")
        assert overall_success_rate(mem_path) == 0.0

    def test_mixed(self, mem_path):
        _rec(mem_path, outcome="SUCCESS")
        _rec(mem_path, outcome="FAILURE")
        assert overall_success_rate(mem_path) == 0.5


# ── retry_rate() ─────────────────────────────────────────────────────────────

class TestRetryRate:
    def test_zero_when_empty(self, mem_path):
        assert retry_rate(mem_path) == 0.0

    def test_zero_when_no_retries(self, mem_path):
        _rec(mem_path, task="task a")
        _rec(mem_path, task="task b")
        assert retry_rate(mem_path) == 0.0

    def test_one_when_all_retried(self, mem_path):
        _rec(mem_path, task="task a", outcome="FAILURE")
        _rec(mem_path, task="task a", outcome="SUCCESS")
        assert retry_rate(mem_path) == 1.0

    def test_partial_retry(self, mem_path):
        _rec(mem_path, task="task a", outcome="FAILURE")
        _rec(mem_path, task="task a", outcome="SUCCESS")
        _rec(mem_path, task="task b", outcome="SUCCESS")
        # 1 out of 2 unique tasks was retried
        assert retry_rate(mem_path) == 0.5


# ── avg_attempts_per_task() ───────────────────────────────────────────────────

class TestAvgAttemptsPerTask:
    def test_zero_when_empty(self, mem_path):
        assert avg_attempts_per_task(mem_path) == 0.0

    def test_one_attempt_each(self, mem_path):
        _rec(mem_path, task="task a")
        _rec(mem_path, task="task b")
        assert avg_attempts_per_task(mem_path) == 1.0

    def test_two_attempts_for_one_task(self, mem_path):
        _rec(mem_path, task="task a", outcome="FAILURE")
        _rec(mem_path, task="task a", outcome="SUCCESS")
        assert avg_attempts_per_task(mem_path) == 2.0

    def test_mixed_attempts(self, mem_path):
        _rec(mem_path, task="task a", outcome="FAILURE")
        _rec(mem_path, task="task a", outcome="SUCCESS")
        _rec(mem_path, task="task b", outcome="SUCCESS")
        # task a: 2, task b: 1 → avg = 1.5
        assert avg_attempts_per_task(mem_path) == 1.5


# ── recent_fingerprints() ─────────────────────────────────────────────────────

class TestRecentFingerprints:
    def test_returns_list(self, mem_path):
        _rec(mem_path, task="task a")
        fps = recent_fingerprints(mem_path)
        assert isinstance(fps, list)

    def test_length_matches_entries(self, mem_path):
        for i in range(5):
            _rec(mem_path, task=f"unique task {i}")
        fps = recent_fingerprints(mem_path, limit=10)
        assert len(fps) == 5

    def test_respects_limit(self, mem_path):
        for i in range(20):
            _rec(mem_path, task=f"unique task {i}")
        fps = recent_fingerprints(mem_path, limit=5)
        assert len(fps) == 5

    def test_empty_when_no_entries(self, mem_path):
        assert recent_fingerprints(mem_path) == []


# ── update_mission() / mission_summary() / all_missions() ────────────────────

class TestMissionTracking:
    def test_creates_mission_record(self, mem_path):
        update_mission(mem_path, "mfp1", "Add authentication", completed=True, blocked=False)
        rec = mission_summary(mem_path, "mfp1")
        assert rec is not None
        assert rec["ok"] == 1

    def test_increments_counters(self, mem_path):
        for _ in range(3):
            update_mission(mem_path, "mfp1", "Mission text", completed=True, blocked=False)
        update_mission(mem_path, "mfp1", "Mission text", completed=False, blocked=True)
        rec = mission_summary(mem_path, "mfp1")
        assert rec["total"] == 4
        assert rec["ok"] == 3
        assert rec["blocked"] == 1

    def test_returns_none_for_unknown_mission(self, mem_path):
        assert mission_summary(mem_path, "unknown_fp") is None

    def test_all_missions_returns_dict(self, mem_path):
        update_mission(mem_path, "mfp1", "Mission A", completed=True, blocked=False)
        update_mission(mem_path, "mfp2", "Mission B", completed=False, blocked=True)
        all_m = all_missions(mem_path)
        assert "mfp1" in all_m
        assert "mfp2" in all_m

    def test_preview_stored(self, mem_path):
        update_mission(mem_path, "mfp1", "Add authentication system", completed=True, blocked=False)
        rec = mission_summary(mem_path, "mfp1")
        assert "authentication" in rec["preview"]


# ── failure_count() ───────────────────────────────────────────────────────────

class TestFailureCount:
    def test_zero_for_unknown(self, mem_path):
        assert failure_count(mem_path, "unknown") == 0

    def test_counts_failures_only(self, mem_path):
        _rec(mem_path, task="task", outcome="FAILURE")
        _rec(mem_path, task="task", outcome="FAILURE")
        _rec(mem_path, task="task", outcome="SUCCESS")
        from romyq.fingerprint import fingerprint as fp
        assert failure_count(mem_path, fp("task")) == 2
