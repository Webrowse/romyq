"""Tests for workspace rollback() — the public function added to validator.py.

Verifies:
- rollback() with pre_dirty=False calls _restore() (git checkout + clean)
- rollback() with pre_dirty=True calls _selective_restore()
- Pre-existing dirty files are preserved through rollback
- Claude-added files are removed by rollback
- Claude-modified tracked files are reverted by rollback
- rollback() is idempotent on a clean workspace
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from romyq.validator import rollback


# ── git repo fixture ──────────────────────────────────────────────────────────

@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True, env=env)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, capture_output=True)
    (tmp_path / "existing.py").write_text("# original\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, env=env)
    return tmp_path


# ── rollback on clean workspace ───────────────────────────────────────────────

class TestRollbackCleanWorkspace:

    def test_rollback_on_clean_workspace_is_idempotent(self, git_repo):
        """rollback() on an already-clean workspace leaves it clean."""
        rollback(str(git_repo))
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=git_repo, capture_output=True, text=True,
        )
        assert r.stdout.strip() == ""

    def test_rollback_removes_untracked_file(self, git_repo):
        """An untracked file added by Claude is deleted on rollback."""
        (git_repo / "claude_new_file.py").write_text("new file")
        rollback(str(git_repo))
        assert not (git_repo / "claude_new_file.py").exists()

    def test_rollback_reverts_modified_tracked_file(self, git_repo):
        """A tracked file modified by Claude is reverted to its original content."""
        (git_repo / "existing.py").write_text("modified by claude\n")
        rollback(str(git_repo))
        assert (git_repo / "existing.py").read_text() == "# original\n"

    def test_rollback_cleans_entire_tree(self, git_repo):
        """After rollback, git status --porcelain reports no changes."""
        (git_repo / "new1.py").write_text("a")
        (git_repo / "new2.py").write_text("b")
        (git_repo / "existing.py").write_text("modified")
        rollback(str(git_repo))
        r = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=git_repo, capture_output=True, text=True,
        )
        assert r.stdout.strip() == ""


# ── rollback with pre-existing dirty files ────────────────────────────────────

class TestRollbackPreDirty:

    def test_pre_existing_file_preserved_on_rollback(self, git_repo):
        """User's pre-existing changes are not touched when pre_dirty=True."""
        (git_repo / "user_work.py").write_text("important user code")
        pre_paths = frozenset(["user_work.py"])

        # Claude adds another file
        (git_repo / "claude_file.py").write_text("claude added this")

        rollback(str(git_repo), pre_dirty=True, pre_dirty_paths=pre_paths)

        assert (git_repo / "user_work.py").read_text() == "important user code"
        assert not (git_repo / "claude_file.py").exists()

    def test_claude_modifications_reverted_while_preserving_user_changes(self, git_repo):
        """Claude's tracked-file edits are reverted; user's new untracked file stays."""
        (git_repo / "user_notes.txt").write_text("my notes")
        pre_paths = frozenset(["user_notes.txt"])

        # Claude modifies existing.py
        (git_repo / "existing.py").write_text("claude modified this")

        rollback(str(git_repo), pre_dirty=True, pre_dirty_paths=pre_paths)

        assert (git_repo / "existing.py").read_text() == "# original\n"
        assert (git_repo / "user_notes.txt").read_text() == "my notes"

    def test_rollback_called_with_correct_arguments(self, git_repo):
        """rollback() with pre_dirty dispatches to _selective_restore, not _restore."""
        (git_repo / "user.txt").write_text("user data")
        pre_paths = frozenset(["user.txt"])
        (git_repo / "claude.txt").write_text("claude data")

        with patch("romyq.validator._selective_restore") as mock_selective, \
             patch("romyq.validator._restore") as mock_restore:
            rollback(str(git_repo), pre_dirty=True, pre_dirty_paths=pre_paths)

        mock_selective.assert_called_once_with(str(git_repo), pre_paths)
        mock_restore.assert_not_called()

    def test_rollback_without_pre_dirty_calls_restore(self, git_repo):
        """rollback() with pre_dirty=False (default) calls _restore(), not selective."""
        with patch("romyq.validator._restore") as mock_restore, \
             patch("romyq.validator._selective_restore") as mock_selective:
            rollback(str(git_repo))

        mock_restore.assert_called_once_with(str(git_repo))
        mock_selective.assert_not_called()


# ── rollback with nested directories ─────────────────────────────────────────

class TestRollbackNestedPaths:

    def test_rollback_removes_nested_untracked_directory(self, git_repo):
        """Claude-created directories and their contents are removed."""
        nested = git_repo / "src" / "new_module"
        nested.mkdir(parents=True)
        (nested / "module.py").write_text("code")
        rollback(str(git_repo))
        assert not nested.exists()

    def test_rollback_removes_multiple_untracked_files(self, git_repo):
        """Multiple untracked files are all removed."""
        for i in range(5):
            (git_repo / f"claude_{i}.py").write_text(f"file {i}")
        rollback(str(git_repo))
        for i in range(5):
            assert not (git_repo / f"claude_{i}.py").exists()
