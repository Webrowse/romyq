"""Tests for Task 6: Append-only event log.

Verifies:
- emit() writes NDJSON entries that survive restarts
- tail() returns the last N events
- emit() never raises (corrupt file, permission errors are swallowed)
- count_by_type() produces accurate summaries
- Events include required timestamp and event_type fields
- Extra keyword arguments are serialised correctly
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq.events import (
    LOOP_STARTED,
    LOOP_STOPPED,
    TASK_COMPLETED,
    TASK_STARTED,
    VALIDATOR_FAILED,
    VALIDATOR_PASSED,
    count_by_type,
    emit,
    tail,
)


@pytest.fixture
def log_path(tmp_path: Path) -> str:
    return str(tmp_path / "events.log")


# ── emit ──────────────────────────────────────────────────────────────────────

class TestEmit:

    def test_creates_log_file(self, log_path):
        emit(log_path, LOOP_STARTED)
        assert Path(log_path).exists()

    def test_writes_valid_json_line(self, log_path):
        emit(log_path, TASK_STARTED, key="abc123")
        lines = Path(log_path).read_text().strip().splitlines()
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == TASK_STARTED
        assert entry["key"] == "abc123"

    def test_timestamp_is_iso_format(self, log_path):
        emit(log_path, LOOP_STARTED)
        entry = json.loads(Path(log_path).read_text().strip())
        ts = entry["ts"]
        assert "T" in ts
        assert len(ts) >= 19

    def test_appends_not_overwrites(self, log_path):
        emit(log_path, LOOP_STARTED)
        emit(log_path, TASK_STARTED, key="k1")
        emit(log_path, TASK_COMPLETED, key="k1")
        lines = Path(log_path).read_text().strip().splitlines()
        assert len(lines) == 3

    def test_extra_kwargs_serialised(self, log_path):
        emit(log_path, VALIDATOR_FAILED, key="abc", reason="timeout", attempts=3)
        entry = json.loads(Path(log_path).read_text().strip())
        assert entry["key"] == "abc"
        assert entry["reason"] == "timeout"
        assert entry["attempts"] == 3

    def test_emit_does_not_raise_on_bad_path(self):
        """emit() to a non-writable path must not propagate exceptions."""
        emit("/no/such/dir/events.log", LOOP_STARTED)  # must not raise

    def test_emit_survives_restart(self, log_path):
        """Entries survive after Python process would restart (just a file check)."""
        emit(log_path, LOOP_STARTED, timeout_s=1800)
        emit(log_path, TASK_STARTED, key="k1")
        content = Path(log_path).read_text()
        entries = [json.loads(l) for l in content.strip().splitlines()]
        assert entries[0]["event"] == LOOP_STARTED
        assert entries[1]["event"] == TASK_STARTED

    def test_newline_delimited_each_entry(self, log_path):
        for _ in range(5):
            emit(log_path, LOOP_STARTED)
        lines = Path(log_path).read_text().splitlines()
        assert len(lines) == 5
        for line in lines:
            json.loads(line)  # each line must be valid JSON


# ── tail ──────────────────────────────────────────────────────────────────────

class TestTail:

    def test_returns_empty_list_when_log_absent(self, tmp_path):
        result = tail(str(tmp_path / "nonexistent.log"), n=10)
        assert result == []

    def test_returns_all_events_when_fewer_than_n(self, log_path):
        emit(log_path, LOOP_STARTED)
        emit(log_path, TASK_STARTED, key="k1")
        result = tail(log_path, n=10)
        assert len(result) == 2

    def test_returns_last_n_events(self, log_path):
        for i in range(20):
            emit(log_path, TASK_STARTED, key=f"k{i}")
        result = tail(log_path, n=5)
        assert len(result) == 5
        assert result[-1]["key"] == "k19"
        assert result[0]["key"] == "k15"

    def test_tail_preserves_order(self, log_path):
        events_sent = [LOOP_STARTED, TASK_STARTED, VALIDATOR_PASSED, TASK_COMPLETED, LOOP_STOPPED]
        for e in events_sent:
            emit(log_path, e)
        result = tail(log_path, n=10)
        assert [r["event"] for r in result] == events_sent

    def test_skips_corrupt_lines(self, log_path):
        Path(log_path).write_text('{"event":"ok","ts":"2026-01-01T00:00:00"}\n{bad}\n{"event":"ok2","ts":"2026-01-01T00:00:01"}\n')
        result = tail(log_path, n=10)
        assert len(result) == 2
        assert result[0]["event"] == "ok"
        assert result[1]["event"] == "ok2"


# ── count_by_type ─────────────────────────────────────────────────────────────

class TestCountByType:

    def test_returns_empty_dict_when_log_absent(self, tmp_path):
        result = count_by_type(str(tmp_path / "nonexistent.log"))
        assert result == {}

    def test_counts_each_event_type(self, log_path):
        emit(log_path, TASK_STARTED, key="k1")
        emit(log_path, TASK_STARTED, key="k2")
        emit(log_path, VALIDATOR_FAILED, key="k1")
        emit(log_path, TASK_COMPLETED, key="k2")
        counts = count_by_type(log_path)
        assert counts[TASK_STARTED] == 2
        assert counts[VALIDATOR_FAILED] == 1
        assert counts[TASK_COMPLETED] == 1

    def test_ignores_corrupt_lines(self, log_path):
        emit(log_path, LOOP_STARTED)
        with open(log_path, "a") as f:
            f.write("{bad}\n")
        counts = count_by_type(log_path)
        assert counts.get(LOOP_STARTED) == 1
