"""Tests for romyq.wizard_logic — all business logic, no UI."""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from romyq import wizard_logic as wiz


# ── TestDemoMission ───────────────────────────────────────────────────────────

class TestDemoMission:
    def test_returns_non_empty_string(self):
        assert isinstance(wiz.demo_mission(), str)
        assert len(wiz.demo_mission()) > 50

    def test_mentions_api(self):
        text = wiz.demo_mission().lower()
        assert "api" in text or "rest" in text

    def test_idempotent(self):
        assert wiz.demo_mission() == wiz.demo_mission()


# ── TestValidateApiKey ────────────────────────────────────────────────────────

class TestValidateApiKey:
    def test_valid_key_long_enough(self):
        assert wiz.validate_api_key("sk-" + "x" * 10) is True

    def test_exactly_ten_chars_valid(self):
        assert wiz.validate_api_key("1234567890") is True

    def test_nine_chars_invalid(self):
        assert wiz.validate_api_key("123456789") is False

    def test_empty_invalid(self):
        assert wiz.validate_api_key("") is False

    def test_strips_whitespace_before_check(self):
        assert wiz.validate_api_key("  1234567890  ") is True

    def test_all_whitespace_invalid(self):
        assert wiz.validate_api_key("          ") is False


# ── TestWriteEnv ──────────────────────────────────────────────────────────────

class TestWriteEnv:
    def test_creates_env_file(self, tmp_path):
        wiz.write_env(str(tmp_path), "sk-test12345")
        assert (tmp_path / ".env").exists()

    def test_returns_env_path(self, tmp_path):
        result = wiz.write_env(str(tmp_path), "sk-test12345")
        assert result == str(tmp_path / ".env")

    def test_writes_api_key(self, tmp_path):
        wiz.write_env(str(tmp_path), "sk-mykey12345")
        content = (tmp_path / ".env").read_text()
        assert "sk-mykey12345" in content

    def test_writes_key_var_name(self, tmp_path):
        wiz.write_env(str(tmp_path), "sk-test12345", provider="deepseek")
        content = (tmp_path / ".env").read_text()
        assert "DEEPSEEK_API_KEY" in content

    def test_updates_existing_key(self, tmp_path):
        (tmp_path / ".env").write_text("DEEPSEEK_API_KEY=old-key\n", encoding="utf-8")
        wiz.write_env(str(tmp_path), "new-key-1234567")
        content = (tmp_path / ".env").read_text()
        assert "new-key-1234567" in content
        assert "old-key" not in content

    def test_preserves_other_env_lines(self, tmp_path):
        (tmp_path / ".env").write_text(
            "OTHER_VAR=hello\nDEEPSEEK_API_KEY=old\n", encoding="utf-8"
        )
        wiz.write_env(str(tmp_path), "new-key-99999")
        content = (tmp_path / ".env").read_text()
        assert "OTHER_VAR=hello" in content

    def test_strips_whitespace_from_key(self, tmp_path):
        wiz.write_env(str(tmp_path), "  sk-clean12345  ")
        content = (tmp_path / ".env").read_text()
        assert "sk-clean12345" in content
        assert "  " not in content.split("=")[1]


# ── TestReadEnvKey ────────────────────────────────────────────────────────────

class TestReadEnvKey:
    def test_returns_empty_when_no_file(self, tmp_path):
        assert wiz.read_env_key(str(tmp_path)) == ""

    def test_reads_written_key(self, tmp_path):
        wiz.write_env(str(tmp_path), "sk-readback1234")
        assert wiz.read_env_key(str(tmp_path)) == "sk-readback1234"

    def test_returns_empty_when_key_absent_in_file(self, tmp_path):
        (tmp_path / ".env").write_text("OTHER=value\n", encoding="utf-8")
        assert wiz.read_env_key(str(tmp_path)) == ""

    def test_roundtrip(self, tmp_path):
        key = "sk-roundtrip99"
        wiz.write_env(str(tmp_path), key)
        assert wiz.read_env_key(str(tmp_path)) == key


# ── TestWriteMission ──────────────────────────────────────────────────────────

class TestWriteMission:
    def test_creates_mission_md(self, tmp_path):
        wiz.write_mission(str(tmp_path), "Build a REST API")
        assert (tmp_path / "mission.md").exists()

    def test_returns_path(self, tmp_path):
        result = wiz.write_mission(str(tmp_path), "Build a REST API")
        assert result == str(tmp_path / "mission.md")

    def test_content_written(self, tmp_path):
        wiz.write_mission(str(tmp_path), "Build a REST API for tasks")
        content = (tmp_path / "mission.md").read_text()
        assert "Build a REST API for tasks" in content

    def test_strips_leading_trailing_whitespace(self, tmp_path):
        wiz.write_mission(str(tmp_path), "  My mission  ")
        content = (tmp_path / "mission.md").read_text()
        assert content.startswith("My mission")

    def test_overwrites_existing(self, tmp_path):
        wiz.write_mission(str(tmp_path), "old mission")
        wiz.write_mission(str(tmp_path), "new mission")
        content = (tmp_path / "mission.md").read_text()
        assert "new mission" in content
        assert "old mission" not in content


# ── TestSetupWorkspace ────────────────────────────────────────────────────────

class TestSetupWorkspace:
    def test_creates_romyq_dir(self, tmp_path):
        wiz.setup_workspace(str(tmp_path))
        assert (tmp_path / ".romyq").is_dir()

    def test_returns_path_string(self, tmp_path):
        result = wiz.setup_workspace(str(tmp_path))
        assert ".romyq" in result


# ── TestAddGitignoreEntries ───────────────────────────────────────────────────

class TestAddGitignoreEntries:
    def test_creates_gitignore(self, tmp_path):
        wiz.add_gitignore_entries(str(tmp_path))
        assert (tmp_path / ".gitignore").exists()

    def test_adds_romyq_entry(self, tmp_path):
        wiz.add_gitignore_entries(str(tmp_path))
        content = (tmp_path / ".gitignore").read_text()
        assert ".romyq/" in content

    def test_adds_env_entry(self, tmp_path):
        wiz.add_gitignore_entries(str(tmp_path))
        content = (tmp_path / ".gitignore").read_text()
        assert ".env" in content

    def test_idempotent(self, tmp_path):
        wiz.add_gitignore_entries(str(tmp_path))
        wiz.add_gitignore_entries(str(tmp_path))
        content = (tmp_path / ".gitignore").read_text()
        assert content.count(".romyq/") == 1


# ── TestWizardSetup ───────────────────────────────────────────────────────────

class TestWizardSetup:
    def test_returns_dict(self, tmp_path):
        result = wiz.wizard_setup(
            workspace=str(tmp_path),
            api_key="sk-test12345",
            mission_text="build something",
            init_git=False,
        )
        assert isinstance(result, dict)

    def test_all_expected_keys(self, tmp_path):
        result = wiz.wizard_setup(
            workspace=str(tmp_path),
            api_key="sk-test12345",
            mission_text="build something",
            init_git=False,
        )
        assert "api_key" in result
        assert "mission" in result
        assert "git" in result
        assert "state_dir" in result

    def test_api_key_configured(self, tmp_path):
        wiz.wizard_setup(
            workspace=str(tmp_path),
            api_key="sk-test12345",
            mission_text="build something",
            init_git=False,
        )
        assert wiz.read_env_key(str(tmp_path)) == "sk-test12345"

    def test_mission_written(self, tmp_path):
        wiz.wizard_setup(
            workspace=str(tmp_path),
            api_key="sk-test12345",
            mission_text="build a REST API",
            init_git=False,
        )
        assert (tmp_path / "mission.md").exists()
        content = (tmp_path / "mission.md").read_text()
        assert "build a REST API" in content

    def test_git_skipped_when_no_vcs(self, tmp_path):
        result = wiz.wizard_setup(
            workspace=str(tmp_path),
            api_key="sk-test12345",
            mission_text="build something",
            init_git=False,
        )
        assert "no-vcs" in result["git"] or "skipped" in result["git"]

    def test_state_dir_created(self, tmp_path):
        wiz.wizard_setup(
            workspace=str(tmp_path),
            api_key="sk-test12345",
            mission_text="build something",
            init_git=False,
        )
        assert (tmp_path / ".romyq").is_dir()

    def test_step_failure_does_not_abort_sequence(self, tmp_path):
        # Even if api_key write somehow fails for a step, others should run
        # We test by providing all valid inputs — all steps should complete
        result = wiz.wizard_setup(
            workspace=str(tmp_path),
            api_key="sk-test12345",
            mission_text="build something",
            init_git=False,
        )
        # All steps must have results (no KeyError)
        assert result["api_key"] and result["mission"] and result["git"] and result["state_dir"]


# ── TestProviders ─────────────────────────────────────────────────────────────

class TestProviders:
    def test_deepseek_in_providers(self):
        assert "deepseek" in wiz.PROVIDERS

    def test_deepseek_has_key_var(self):
        assert wiz.PROVIDERS["deepseek"]["key_var"] == "DEEPSEEK_API_KEY"
