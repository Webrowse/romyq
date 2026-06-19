"""Tests for the validator — Findings 2 and 3.

Finding 2: Validator false-fails already-complete tasks.
  Claude may correctly determine a task is already done and print COMPLETED
  without creating a new commit.  The validator must recognise this as
  NO_ACTION_REQUIRED, not FAILURE.

Finding 3: Dirty repository state compounds across failures.
  When pre-existing uncommitted changes exist, the validator must only clean
  up files Claude added/modified, leaving the user's changes intact.

Three-way outcome contract:
  SUCCESS            — Claude committed work; repo is clean.
  NO_ACTION_REQUIRED — Task already satisfied; no commit needed; advance normally.
  FAILURE            — Something went wrong; workspace restored.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from romyq.validator import (
    FAILURE,
    NO_ACTION_REQUIRED,
    SUCCESS,
    validate,
)


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
    (tmp_path / "readme.txt").write_text("initial")
    subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, capture_output=True, env=env)
    return tmp_path


def _head(repo: Path) -> str:
    r = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=repo, capture_output=True, text=True,
    )
    return r.stdout.strip()


def _make_commit(repo: Path, filename: str = "change.txt", msg: str = "feat: add file") -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    (repo / filename).write_text("content")
    subprocess.run(["git", "add", filename], cwd=repo, capture_output=True, env=env)
    subprocess.run(["git", "commit", "-m", msg], cwd=repo, capture_output=True, env=env)
    return _head(repo)


# ── outcome constants ─────────────────────────────────────────────────────────

class TestOutcomeConstants:

    def test_all_three_constants_are_distinct(self):
        assert SUCCESS != FAILURE
        assert SUCCESS != NO_ACTION_REQUIRED
        assert FAILURE != NO_ACTION_REQUIRED

    def test_constants_are_strings(self):
        assert isinstance(SUCCESS, str)
        assert isinstance(FAILURE, str)
        assert isinstance(NO_ACTION_REQUIRED, str)

    def test_success_is_truthy_and_failure_is_truthy(self):
        """All constants are non-empty strings; check with identity, not truthiness."""
        assert SUCCESS
        assert FAILURE
        assert NO_ACTION_REQUIRED


# ── Finding 2: already-complete task detection ────────────────────────────────

class TestAlreadyCompleteDetection:

    def test_completed_marker_no_new_commit_is_no_action_required(self, git_repo):
        """COMPLETED + returncode 0 + clean tree + same commit → NO_ACTION_REQUIRED."""
        commit = _head(git_repo)
        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=0,
            stdout="I see this feature is already implemented.\nCOMPLETED\n",
        )
        assert outcome == NO_ACTION_REQUIRED
        assert "already complete" in reason.lower()

    def test_completed_marker_with_new_commit_is_success(self, git_repo):
        """When a new commit IS created, outcome is SUCCESS (normal path)."""
        before = _head(git_repo)
        after = _make_commit(git_repo)
        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=before,
            after_commit=after,
            returncode=0,
            stdout="COMPLETED",
        )
        assert outcome == SUCCESS
        assert reason == "Validation passed"

    def test_no_completed_marker_same_commit_is_failure(self, git_repo):
        """Without COMPLETED marker, same commit → FAILURE."""
        commit = _head(git_repo)
        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=0,
            stdout="Did some work but forgot to commit.",
        )
        assert outcome == FAILURE
        assert "no new commit" in reason.lower()

    def test_completed_but_nonzero_returncode_is_failure(self, git_repo):
        """returncode != 0 always → FAILURE, even with COMPLETED in stdout."""
        commit = _head(git_repo)
        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=1,
            stdout="COMPLETED",
        )
        assert outcome == FAILURE
        assert "non-zero" in reason.lower()

    def test_completed_but_new_dirty_files_is_failure(self, git_repo):
        """COMPLETED + new dirty files Claude left behind → FAILURE."""
        commit = _head(git_repo)
        (git_repo / "new_file.txt").write_text("unfinished")
        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=0,
            stdout="COMPLETED",
            pre_dirty=False,
            pre_dirty_paths=frozenset(),
        )
        assert outcome == FAILURE
        assert not (git_repo / "new_file.txt").exists()

    def test_completed_with_only_preexisting_dirty_files_is_no_action_required(self, git_repo):
        """COMPLETED + only pre-existing dirty files remaining → NO_ACTION_REQUIRED."""
        (git_repo / "user_work.txt").write_text("user's changes")
        commit = _head(git_repo)
        pre_dirty_paths = frozenset(["user_work.txt"])

        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=0,
            stdout="This was already done.\nCOMPLETED",
            pre_dirty=True,
            pre_dirty_paths=pre_dirty_paths,
        )
        assert outcome == NO_ACTION_REQUIRED
        assert "already complete" in reason.lower()
        assert (git_repo / "user_work.txt").read_text() == "user's changes"

    def test_completed_uppercase_only_matches(self, git_repo):
        """Lowercase 'completed' does NOT trigger NO_ACTION_REQUIRED."""
        commit = _head(git_repo)
        outcome, _ = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=0,
            stdout="completed the task",
        )
        assert outcome == FAILURE

    def test_regression_observed_infinite_loop_scenario(self, git_repo):
        """Regression: task already done → no commit → validator said FAIL → loop."""
        commit = _head(git_repo)
        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=0,
            stdout=(
                "I'll check the repository...\n"
                "JWT authentication is already implemented in auth/jwt.py.\n"
                "All tests pass. Nothing to do.\n"
                "COMPLETED\n"
            ),
        )
        assert outcome == NO_ACTION_REQUIRED, f"Expected NO_ACTION_REQUIRED but got: {outcome}, reason: {reason}"


# ── Finding 3: selective restore with pre-existing dirty state ────────────────

class TestSelectiveRestore:

    def test_cleans_claude_additions_on_failure(self, git_repo):
        """When Claude fails, its untracked files are cleaned up."""
        commit = _head(git_repo)
        (git_repo / "claude_new_file.txt").write_text("incomplete work")
        outcome, _ = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=1,
        )
        assert outcome == FAILURE
        assert not (git_repo / "claude_new_file.txt").exists()

    def test_preserves_preexisting_untracked_file_on_failure(self, git_repo):
        """Pre-existing untracked file is left alone when Claude fails."""
        (git_repo / "my_notes.txt").write_text("my notes")
        commit = _head(git_repo)
        pre_dirty_paths = frozenset(["my_notes.txt"])

        (git_repo / "claude_file.txt").write_text("claude's junk")
        outcome, _ = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=1,
            pre_dirty=True,
            pre_dirty_paths=pre_dirty_paths,
        )
        assert outcome == FAILURE
        assert not (git_repo / "claude_file.txt").exists()
        assert (git_repo / "my_notes.txt").read_text() == "my notes"

    def test_preserves_preexisting_modified_tracked_file_on_failure(self, git_repo):
        """Pre-existing tracked modification is left alone when Claude fails."""
        (git_repo / "readme.txt").write_text("user modified this")
        commit = _head(git_repo)
        pre_dirty_paths = frozenset(["readme.txt"])

        (git_repo / "claude_output.txt").write_text("failed output")
        outcome, _ = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=1,
            pre_dirty=True,
            pre_dirty_paths=pre_dirty_paths,
        )
        assert outcome == FAILURE
        assert not (git_repo / "claude_output.txt").exists()
        assert (git_repo / "readme.txt").read_text() == "user modified this"

    def test_cleans_multiple_claude_additions_on_failure(self, git_repo):
        """All of Claude's new files are cleaned, none of the user's."""
        (git_repo / "user_draft.txt").write_text("draft")
        commit = _head(git_repo)
        pre_dirty_paths = frozenset(["user_draft.txt"])

        (git_repo / "claude_a.txt").write_text("a")
        (git_repo / "claude_b.txt").write_text("b")
        (git_repo / "claude_c.txt").write_text("c")

        outcome, _ = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=1,
            pre_dirty=True,
            pre_dirty_paths=pre_dirty_paths,
        )
        assert outcome == FAILURE
        assert not (git_repo / "claude_a.txt").exists()
        assert not (git_repo / "claude_b.txt").exists()
        assert not (git_repo / "claude_c.txt").exists()
        assert (git_repo / "user_draft.txt").read_text() == "draft"

    def test_regression_dirty_state_does_not_compound(self, git_repo):
        """Regression: successive failures with pre_dirty do not accumulate dirty files.

        Before the fix: safe_restore() was skipped entirely when pre_dirty=True,
        so Claude's failed changes from iteration N remained in the tree for N+1.
        After the fix: selective restore cleans Claude's additions each iteration.
        """
        (git_repo / "user_file.txt").write_text("user work")
        commit = _head(git_repo)
        pre_dirty_paths = frozenset(["user_file.txt"])

        (git_repo / "iter1_file.txt").write_text("iteration 1 junk")
        validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=1,
            pre_dirty=True,
            pre_dirty_paths=pre_dirty_paths,
        )
        assert not (git_repo / "iter1_file.txt").exists()
        assert (git_repo / "user_file.txt").exists()

        (git_repo / "iter2_file.txt").write_text("iteration 2 junk")
        validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=1,
            pre_dirty=True,
            pre_dirty_paths=pre_dirty_paths,
        )
        assert not (git_repo / "iter1_file.txt").exists()
        assert not (git_repo / "iter2_file.txt").exists()
        assert (git_repo / "user_file.txt").exists()

    def test_failure_message_mentions_preexisting_preservation(self, git_repo):
        """FAILURE reason tells the user their changes are preserved."""
        commit = _head(git_repo)
        (git_repo / "user.txt").write_text("user")
        pre_dirty_paths = frozenset(["user.txt"])

        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=1,
            pre_dirty=True,
            pre_dirty_paths=pre_dirty_paths,
        )
        assert outcome == FAILURE
        assert "preserved" in reason.lower()

    def test_no_preexisting_changes_uses_full_restore(self, git_repo):
        """When pre_dirty=False, the full restore still works correctly."""
        commit = _head(git_repo)
        (git_repo / "readme.txt").write_text("claude changed this")
        (git_repo / "new_from_claude.txt").write_text("new file")

        outcome, _ = validate(
            workspace=str(git_repo),
            before_commit=commit,
            after_commit=commit,
            returncode=1,
            pre_dirty=False,
        )
        assert outcome == FAILURE
        assert (git_repo / "readme.txt").read_text() == "initial"
        assert not (git_repo / "new_from_claude.txt").exists()


# ── SUCCESS path ──────────────────────────────────────────────────────────────

class TestSuccessPath:

    def test_new_commit_clean_tree_is_success(self, git_repo):
        """New commit + clean tree → SUCCESS."""
        before = _head(git_repo)
        after = _make_commit(git_repo)
        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=before,
            after_commit=after,
            returncode=0,
        )
        assert outcome == SUCCESS
        assert reason == "Validation passed"

    def test_new_commit_dirty_tree_is_failure(self, git_repo):
        """New commit but dirty tree (Claude didn't stage everything) → FAILURE."""
        before = _head(git_repo)
        after = _make_commit(git_repo)
        (git_repo / "unstaged.txt").write_text("oops")
        outcome, reason = validate(
            workspace=str(git_repo),
            before_commit=before,
            after_commit=after,
            returncode=0,
        )
        assert outcome == FAILURE
        assert "dirty" in reason.lower()

    def test_nonzero_returncode_always_failure(self, git_repo):
        """Non-zero returncode → FAILURE regardless of commit state."""
        before = _head(git_repo)
        after = _make_commit(git_repo)
        outcome, _ = validate(
            workspace=str(git_repo),
            before_commit=before,
            after_commit=after,
            returncode=1,
        )
        assert outcome == FAILURE
