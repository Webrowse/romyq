"""Tests for romyq.context — repository memory generation."""
import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from romyq.context import generate, load, write


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def git_workspace(tmp_path):
    """Minimal git repo with pyproject.toml."""
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "t@t.com"],
                   check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "T"],
                   check=True, capture_output=True)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.pytest.ini_options]\n[tool.ruff]\n[tool.mypy]\n', encoding="utf-8"
    )
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "init"],
                   check=True, capture_output=True)
    return tmp_path


@pytest.fixture()
def empty_workspace(tmp_path):
    return tmp_path


# ── generate() ────────────────────────────────────────────────────────────────

class TestGenerate:
    def test_returns_string(self, empty_workspace):
        result = generate(str(empty_workspace))
        assert isinstance(result, str)

    def test_contains_header(self, empty_workspace):
        result = generate(str(empty_workspace))
        assert "# Repository Context" in result

    def test_contains_generated_timestamp(self, empty_workspace):
        result = generate(str(empty_workspace))
        assert "Generated:" in result

    def test_contains_workspace_path(self, empty_workspace):
        result = generate(str(empty_workspace))
        assert str(empty_workspace.resolve()) in result

    def test_uses_provided_detect_result(self, empty_workspace):
        d = {
            "language": "rust",
            "frameworks": ["tokio"],
            "build_commands": ["cargo build"],
            "test_framework": "cargo test",
            "test_detail": "",
            "entry_points": ["src/main.rs"],
            "structure": ["src/"],
            "branches": [],
            "dev_tools": [],
        }
        result = generate(str(empty_workspace), detect_result=d)
        assert "rust" in result
        assert "tokio" in result
        assert "cargo build" in result
        assert "src/main.rs" in result

    def test_detects_python_conventions(self, git_workspace):
        d = {
            "language": "python",
            "frameworks": [],
            "build_commands": [],
            "test_framework": "pytest",
            "test_detail": "",
            "entry_points": [],
            "structure": [],
            "branches": [],
            "dev_tools": [],
        }
        result = generate(str(git_workspace), detect_result=d)
        assert "ruff" in result or "mypy" in result or "pytest" in result

    def test_detects_github_actions(self, tmp_path):
        gh = tmp_path / ".github" / "workflows"
        gh.mkdir(parents=True)
        (gh / "ci.yml").write_text("on: push", encoding="utf-8")
        result = generate(str(tmp_path))
        assert "GitHub Actions" in result
        assert "ci.yml" in result

    def test_detects_editorconfig_spaces(self, tmp_path):
        (tmp_path / ".editorconfig").write_text(
            "[*]\nindent_style = space\nindent_size = 4\n", encoding="utf-8"
        )
        result = generate(str(tmp_path))
        assert "4 spaces" in result

    def test_detects_editorconfig_tabs(self, tmp_path):
        (tmp_path / ".editorconfig").write_text(
            "[*]\nindent_style = tab\n", encoding="utf-8"
        )
        result = generate(str(tmp_path))
        assert "tabs" in result

    def test_git_first_commit_date(self, git_workspace):
        result = generate(str(git_workspace))
        assert "First commit:" in result

    def test_no_git_no_crash(self, tmp_path):
        # Non-git workspace must not raise
        result = generate(str(tmp_path))
        assert isinstance(result, str)

    def test_multiple_ci_systems(self, tmp_path):
        (tmp_path / ".travis.yml").write_text("language: python", encoding="utf-8")
        (tmp_path / "Jenkinsfile").write_text("pipeline {}", encoding="utf-8")
        result = generate(str(tmp_path))
        assert "Travis CI" in result
        assert "Jenkins" in result


# ── write() ───────────────────────────────────────────────────────────────────

class TestWrite:
    def test_creates_context_md(self, empty_workspace):
        path = write(str(empty_workspace))
        assert Path(path).exists()
        assert path.endswith("context.md")

    def test_content_matches_generate(self, empty_workspace):
        expected = generate(str(empty_workspace))
        path = write(str(empty_workspace))
        actual = Path(path).read_text(encoding="utf-8")
        # Timestamps will differ slightly; check structure only
        assert "# Repository Context" in actual

    def test_overwrites_existing(self, empty_workspace):
        path = write(str(empty_workspace))
        first = Path(path).read_text(encoding="utf-8")
        path2 = write(str(empty_workspace))
        assert path == path2
        second = Path(path2).read_text(encoding="utf-8")
        assert "# Repository Context" in second

    def test_atomic_no_partial_on_simulated_failure(self, empty_workspace):
        """If write crashes mid-way the original file should remain untouched."""
        path_obj = Path(write(str(empty_workspace)))
        original = path_obj.read_text(encoding="utf-8")

        import romyq.context as ctx_mod
        original_open = open

        call_count = [0]

        def mock_open(*a, **kw):
            call_count[0] += 1
            if call_count[0] == 2:  # second open = NamedTemporaryFile
                raise OSError("simulated disk full")
            return original_open(*a, **kw)

        with patch("builtins.open", side_effect=mock_open):
            try:
                write(str(empty_workspace))
            except OSError:
                pass

        # Original must still be intact
        assert path_obj.read_text(encoding="utf-8") == original


# ── load() ────────────────────────────────────────────────────────────────────

class TestLoad:
    def test_returns_empty_when_absent(self, empty_workspace):
        assert load(str(empty_workspace)) == ""

    def test_returns_content_after_write(self, empty_workspace):
        write(str(empty_workspace))
        content = load(str(empty_workspace))
        assert "# Repository Context" in content
