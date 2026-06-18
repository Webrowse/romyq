"""Regression tests for romyq init flow consistency.

After `romyq init`:
  - mission.md must exist inside the workspace directory
  - .romyq/ must exist inside the workspace directory
  - `romyq doctor` checks (git repo, mission.md, .romyq/) must all pass
  - `romyq run` must be able to find mission.md immediately

All tests use a fresh temporary directory so they are isolated from
the project's own git repo and filesystem state.
"""
import subprocess
from pathlib import Path

import pytest

from romyq import store
from romyq.mission import create_template, exists as mission_exists
from romyq.workspace import bootstrap, is_git_repo


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Isolated temp dir with git identity set so commits succeed."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ── Test 1: romyq init && romyq doctor must succeed ──────────────────────────

def test_init_creates_git_repo(workspace):
    bootstrap(str(workspace))
    assert is_git_repo(str(workspace)), ".git/ was not created by bootstrap()"


def test_init_creates_romyq_dir(workspace):
    store.ensure_dir(str(workspace))
    assert (workspace / ".romyq").is_dir(), ".romyq/ was not created by ensure_dir()"


def test_init_creates_mission_md(workspace):
    create_template(str(workspace))
    assert (workspace / "mission.md").exists(), "mission.md was not created in workspace"


def test_doctor_passes_after_init(workspace):
    """All three doctor checks must pass: git repo, .romyq/, mission.md."""
    bootstrap(str(workspace))
    store.ensure_dir(str(workspace))
    create_template(str(workspace))

    assert is_git_repo(str(workspace)), "doctor check: workspace is not a git repo"
    assert store.romyq_dir(str(workspace)).exists(), "doctor check: .romyq/ missing"
    assert mission_exists(str(workspace)), "doctor check: mission.md missing"


# ── Test 2: romyq init && romyq info must show valid state ───────────────────

def test_info_finds_state_after_init(workspace):
    bootstrap(str(workspace))
    store.ensure_dir(str(workspace))
    create_template(str(workspace))

    # info reads state from .romyq/state.json (created lazily on first access)
    state_path = store.state_path(str(workspace))
    assert Path(state_path).parent.is_dir(), "info check: .romyq/ dir missing"
    assert mission_exists(str(workspace)), "info check: mission.md missing"


# ── Test 3: mission.md must be in workspace, not parent ──────────────────────

def test_mission_in_workspace_not_parent(tmp_path, monkeypatch):
    """When init targets a subdirectory, mission.md goes inside it — not in CWD."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

    sub = tmp_path / "myproject"
    sub.mkdir()

    create_template(str(sub))

    assert (sub / "mission.md").exists(), "mission.md not found inside workspace subdirectory"
    assert not (tmp_path / "mission.md").exists(), "mission.md leaked into parent directory"


# ── Test 4: .romyq must be in workspace, not parent ──────────────────────────

def test_romyq_dir_in_workspace_not_parent(tmp_path, monkeypatch):
    """When init targets a subdirectory, .romyq/ goes inside it — not in CWD."""
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

    sub = tmp_path / "myproject"
    sub.mkdir()

    store.ensure_dir(str(sub))

    assert (sub / ".romyq").is_dir(), ".romyq/ not found inside workspace subdirectory"
    assert not (tmp_path / ".romyq").exists(), ".romyq/ leaked into parent directory"


# ── Test 5: romyq run can proceed immediately after init ─────────────────────

def test_run_prerequisites_satisfied_after_init(workspace):
    """romyq run checks: mission_exists() + is_git_repo() + .romyq/ present.
    All must pass without any manual step after init."""
    bootstrap(str(workspace))
    store.ensure_dir(str(workspace))
    create_template(str(workspace))

    # romyq run calls mission_exists() in CWD; workspace IS CWD here (monkeypatched above)
    assert mission_exists("."), "romyq run would abort: mission.md not found in CWD"
    assert is_git_repo(str(workspace)), "romyq run would fail: workspace is not a git repo"
    assert store.romyq_dir(str(workspace)).exists(), "romyq run would fail: .romyq/ missing"

    # Confirm state path is writable (state.json will be written on first run)
    state_path = store.state_path(str(workspace))
    assert Path(state_path).parent.is_dir(), "state directory not accessible"
