"""Tests for atomic write guarantees across all JSON persistence paths.

Verifies:
- state.py save() uses fsync + os.replace() atomicity
- findings.py _save() uses fsync + os.replace() atomicity
- history.py _save() uses fsync + os.replace() atomicity
- events.py prune() uses fsync + os.replace() atomicity
- A concurrent reader never sees a partial write (tmp file is only visible
  under its .tmp name, never under the real name until os.replace())
- Pruning removes oldest events and preserves exactly max_entries
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import call, patch

import pytest

from romyq.events import emit, prune
from romyq.findings import add_finding
from romyq.history import add_entry
from romyq.state import DEFAULT_STATE, load as load_state, save as save_state


# ── helpers ───────────────────────────────────────────────────────────────────

def _count_tmp_files(directory: Path) -> int:
    return len(list(directory.glob("*.tmp")))


# ── state.py ─────────────────────────────────────────────────────────────────

class TestStateAtomicWrite:

    def test_save_uses_os_replace(self, tmp_path):
        """os.replace() is called once per save(), making the write atomic."""
        sf = str(tmp_path / "state.json")
        state = DEFAULT_STATE.copy()

        replaced: list[tuple] = []
        real_replace = os.replace

        def spy_replace(src, dst):
            replaced.append((src, dst))
            real_replace(src, dst)

        with patch("romyq.state.os.replace", side_effect=spy_replace):
            save_state(state, sf)

        assert len(replaced) == 1
        src, dst = replaced[0]
        assert dst == sf
        assert src.endswith(".tmp")

    def test_save_calls_fsync(self, tmp_path):
        """fsync() is called on the temp file descriptor before os.replace."""
        sf = str(tmp_path / "state.json")
        state = DEFAULT_STATE.copy()

        fsync_calls: list[int] = []
        real_fsync = os.fsync

        def spy_fsync(fd):
            fsync_calls.append(fd)
            real_fsync(fd)

        with patch("romyq.state.os.fsync", side_effect=spy_fsync):
            save_state(state, sf)

        assert len(fsync_calls) == 1

    def test_no_tmp_files_left_after_save(self, tmp_path):
        """No .tmp files remain after a successful save."""
        sf = str(tmp_path / "state.json")
        save_state(DEFAULT_STATE.copy(), sf)
        assert _count_tmp_files(tmp_path) == 0

    def test_save_produces_valid_json(self, tmp_path):
        """The written file is valid JSON containing all expected fields."""
        sf = str(tmp_path / "state.json")
        state = DEFAULT_STATE.copy()
        state["tasks_completed"] = 42
        save_state(state, sf)
        with open(sf) as f:
            data = json.load(f)
        assert data["tasks_completed"] == 42

    def test_reload_after_save_matches_original(self, tmp_path):
        """load() after save() returns the same state."""
        sf = str(tmp_path / "state.json")
        state = DEFAULT_STATE.copy()
        state["consecutive_failures"] = 7
        state["last_failure_reason"] = "test"
        save_state(state, sf)
        reloaded = load_state(sf)
        assert reloaded["consecutive_failures"] == 7
        assert reloaded["last_failure_reason"] == "test"


# ── findings.py ──────────────────────────────────────────────────────────────

class TestFindingsAtomicWrite:

    def test_add_finding_uses_os_replace(self, tmp_path):
        fp = str(tmp_path / "findings.json")
        replaced: list[tuple] = []
        real_replace = os.replace

        def spy(src, dst):
            replaced.append((src, dst))
            real_replace(src, dst)

        with patch("romyq.findings.os.replace", side_effect=spy):
            add_finding("title", "description", "high", fp)

        assert len(replaced) == 1
        assert replaced[0][1] == fp

    def test_add_finding_calls_fsync(self, tmp_path):
        fp = str(tmp_path / "findings.json")
        fsync_calls: list[int] = []
        real_fsync = os.fsync

        def spy(fd):
            fsync_calls.append(fd)
            real_fsync(fd)

        with patch("romyq.findings.os.fsync", side_effect=spy):
            add_finding("title", "description", "high", fp)

        assert len(fsync_calls) == 1

    def test_no_tmp_files_left_after_add_finding(self, tmp_path):
        fp = str(tmp_path / "findings.json")
        add_finding("t", "d", "low", fp)
        assert _count_tmp_files(tmp_path) == 0


# ── history.py ───────────────────────────────────────────────────────────────

class TestHistoryAtomicWrite:

    def test_add_entry_uses_os_replace(self, tmp_path):
        hp = str(tmp_path / "history.json")
        replaced: list[tuple] = []
        real_replace = os.replace

        def spy(src, dst):
            replaced.append((src, dst))
            real_replace(src, dst)

        with patch("romyq.history.os.replace", side_effect=spy):
            add_entry("task", "implementation", True, "abc123", "ok", hp)

        assert len(replaced) == 1
        assert replaced[0][1] == hp

    def test_add_entry_calls_fsync(self, tmp_path):
        hp = str(tmp_path / "history.json")
        fsync_calls: list[int] = []
        real_fsync = os.fsync

        def spy(fd):
            fsync_calls.append(fd)
            real_fsync(fd)

        with patch("romyq.history.os.fsync", side_effect=spy):
            add_entry("task", "implementation", True, "abc123", "ok", hp)

        assert len(fsync_calls) == 1

    def test_no_tmp_files_left_after_add_entry(self, tmp_path):
        hp = str(tmp_path / "history.json")
        add_entry("task", "implementation", True, "abc123", "ok", hp)
        assert _count_tmp_files(tmp_path) == 0


# ── events.py prune() ────────────────────────────────────────────────────────

class TestEventsPrune:

    def test_prune_returns_zero_when_file_absent(self, tmp_path):
        path = str(tmp_path / "events.log")
        assert prune(path, max_entries=100) == 0

    def test_prune_returns_zero_when_within_limit(self, tmp_path):
        path = str(tmp_path / "events.log")
        for i in range(5):
            emit(path, "task_started", key=f"k{i}")
        assert prune(path, max_entries=10) == 0

    def test_prune_removes_oldest_entries(self, tmp_path):
        path = str(tmp_path / "events.log")
        for i in range(20):
            emit(path, "task_started", key=f"k{i}")
        removed = prune(path, max_entries=10)
        assert removed == 10
        lines = Path(path).read_text().strip().splitlines()
        assert len(lines) == 10
        last = json.loads(lines[-1])
        assert last["key"] == "k19"
        first = json.loads(lines[0])
        assert first["key"] == "k10"

    def test_prune_uses_atomic_replace(self, tmp_path):
        path = str(tmp_path / "events.log")
        for i in range(20):
            emit(path, "task_started", key=f"k{i}")
        replaced: list[tuple] = []
        real_replace = os.replace

        def spy(src, dst):
            replaced.append((src, dst))
            real_replace(src, dst)

        with patch("romyq.events.os.replace", side_effect=spy):
            prune(path, max_entries=10)

        assert len(replaced) == 1
        assert replaced[0][1] == path
        assert replaced[0][0].endswith(".tmp")

    def test_prune_calls_fsync(self, tmp_path):
        path = str(tmp_path / "events.log")
        for i in range(20):
            emit(path, "task_started", key=f"k{i}")
        fsync_calls: list[int] = []
        real_fsync = os.fsync

        def spy(fd):
            fsync_calls.append(fd)
            real_fsync(fd)

        with patch("romyq.events.os.fsync", side_effect=spy):
            prune(path, max_entries=10)

        assert len(fsync_calls) == 1

    def test_prune_does_not_raise_on_corrupt_lines(self, tmp_path):
        path = str(tmp_path / "events.log")
        for i in range(15):
            emit(path, "task_started", key=f"k{i}")
        with open(path, "a") as f:
            f.write("{not json}\n")
        removed = prune(path, max_entries=10)
        assert removed == 6  # 15 valid + 1 corrupt = 16 total; remove 6

    def test_prune_no_tmp_files_left(self, tmp_path):
        path = str(tmp_path / "events.log")
        for i in range(20):
            emit(path, "task_started", key=f"k{i}")
        prune(path, max_entries=10)
        assert _count_tmp_files(tmp_path) == 0
