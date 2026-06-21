"""Regression tests for romyq init path resolution crash (Python 3.14).

cmd_init() crashed at Path(workspace_path).resolve() when the target
directory did not exist or the CWD was deleted from another terminal.
resolve() calls os.getcwd() internally for relative paths, which fails
when the CWD is inaccessible.

Fix: _safe_absolute() avoids resolve() entirely.  It only calls os.getcwd()
inside a try/except with a fallback to the $PWD environment variable, then
joins paths manually without touching the filesystem.
"""
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from romyq.cli import _resolve_workspace, _safe_absolute


# ── _resolve_workspace ────────────────────────────────────────────────────────

class TestResolveWorkspace:
    def test_defaults_to_current_dir(self):
        class Args:
            workspace = None
        assert _resolve_workspace(Args()) == "."

    def test_uses_arg_when_given(self):
        class Args:
            workspace = "/some/path"
        assert _resolve_workspace(Args()) == "/some/path"

    def test_uses_env_var_when_no_arg(self, monkeypatch):
        monkeypatch.setenv("ROMYQ_WORKSPACE", "/env/path")
        class Args:
            workspace = None
        assert _resolve_workspace(Args()) == "/env/path"

    def test_arg_trumps_env_var(self, monkeypatch):
        monkeypatch.setenv("ROMYQ_WORKSPACE", "/env/path")
        class Args:
            workspace = "/arg/path"
        assert _resolve_workspace(Args()) == "/arg/path"

    def test_empty_env_var_returns_empty(self, monkeypatch):
        """ROMYQ_WORKSPACE='' is falsy but getenv('') returns ''."""
        monkeypatch.setenv("ROMYQ_WORKSPACE", "")
        class Args:
            workspace = None
        assert _resolve_workspace(Args()) == ""


# ── _safe_absolute with non-existent paths ────────────────────────────────────

class TestSafeAbsolute:
    """_safe_absolute must handle non-existent paths without error."""

    def test_existing_directory(self, tmp_path):
        p = _safe_absolute(str(tmp_path))
        assert p == tmp_path

    def test_non_existent_absolute(self):
        p = _safe_absolute("/tmp/romyq_test_nonexistent_XXXX")
        assert str(p).endswith("/tmp/romyq_test_nonexistent_XXXX")

    def test_non_existent_relative(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = _safe_absolute("new_project_dir")
        assert str(p) == str(tmp_path / "new_project_dir")

    def test_non_existent_with_parents(self):
        p = _safe_absolute("/tmp/romyq_a/romyq_b/romyq_c")
        assert str(p).endswith("romyq_a/romyq_b/romyq_c")

    def test_empty_string_resolves_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = _safe_absolute("")
        assert p == tmp_path

    def test_dot_resolves_to_cwd(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        p = _safe_absolute(".")
        assert p == tmp_path

    def test_relative_with_dotdot_preserved(self, tmp_path, monkeypatch):
        """_safe_absolute does NOT resolve .. — that's intentional.
        The Path is still usable; mkdir() and the OS handle .. resolution."""
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        monkeypatch.chdir(sub)
        p = _safe_absolute("../..")
        # .. is preserved as a path component; mkdir works because the OS
        # resolves it.  Compare via normpath to verify the target.
        assert os.path.normpath(p) == os.path.normpath(tmp_path)

    def test_broken_cwd_uses_subprocess(self, tmp_path):
        """_safe_absolute falls back to $PWD when os.getcwd() fails (deleted CWD).
        Run in a subprocess so the deleted CWD doesn't affect pytest itself."""
        code = """
import os, sys
sys.path.insert(0, {project!r})
from pathlib import Path
from romyq.cli import _safe_absolute

# Delete CWD, then call _safe_absolute
os.chdir({target!r})
os.rmdir({target!r})

try:
    p = _safe_absolute("subdir")
    # Should use $PWD as fallback
    expected = Path(os.environ["PWD"]) / "subdir"
    assert str(p) == str(expected), f"{{p}} != {{expected}}"
    print("PASS")
except Exception as e:
    print(f"FAIL: {{type(e).__name__}}: {{e}}")
    sys.exit(1)
""".format(project=str(Path(__file__).resolve().parent.parent), target=str(tmp_path))
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=10,
            env={**os.environ, "PWD": str(tmp_path)},
        )
        assert result.returncode == 0, f"Subprocess failed: {result.stderr}"


# ── cmd_init path resolution ──────────────────────────────────────────────────

class TestCmdInitResolve:
    """cmd_init must not crash when the target directory does not exist."""

    def test_init_existing_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

        from romyq.cli import cmd_init

        class Args:
            workspace = str(tmp_path)
            no_vcs = False
            no_wizard = True

        cmd_init(Args())
        assert (tmp_path / "mission.md").exists()

    def test_init_non_existent_dir(self, tmp_path, monkeypatch):
        """The crash scenario: init /path/to/new-project where dir doesn't exist."""
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

        target = tmp_path / "romyq_new_project"
        assert not target.exists()

        from romyq.cli import cmd_init

        class Args:
            workspace = str(target)
            no_vcs = False
            no_wizard = True

        cmd_init(Args())
        assert target.is_dir()
        assert (target / "mission.md").exists()

    def test_init_absolute_path_non_existent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

        target = tmp_path / "abs_project"
        assert not target.exists()

        from romyq.cli import cmd_init

        class Args:
            workspace = str(target.absolute())
            no_vcs = False
            no_wizard = True

        cmd_init(Args())
        assert target.is_dir()

    def test_init_relative_path(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

        from romyq.cli import cmd_init

        class Args:
            workspace = "my_relative_project"
            no_vcs = False
            no_wizard = True

        cmd_init(Args())
        assert (tmp_path / "my_relative_project").is_dir()

    def test_init_empty_env_no_crash(self, tmp_path, monkeypatch):
        """ROMYQ_WORKSPACE=\"\" must not cause crash."""
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("ROMYQ_WORKSPACE", "")
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

        from romyq.cli import cmd_init

        class Args:
            workspace = None
            no_vcs = False
            no_wizard = True

        cmd_init(Args())
        assert (tmp_path / "mission.md").exists()

    def test_init_wizard_does_not_crash_on_non_existent_dir(self, tmp_path, monkeypatch):
        """The wizard code path (no_wizard=False) must not crash before the wizard."""
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

        target = tmp_path / "wizard_project"
        assert not target.exists()

        with patch("romyq.wizard.run_wizard") as mock_wizard:
            from romyq.cli import cmd_init

            class Args:
                workspace = str(target)
                no_vcs = False
                no_wizard = False

            cmd_init(Args())

        mock_wizard.assert_called_once()
        args, kwargs = mock_wizard.call_args
        assert "workspace" in kwargs
        assert target.is_dir()

    def test_init_deleted_cwd_subprocess(self, tmp_path, monkeypatch):
        """Run init in a subprocess where the CWD is deleted before the call.
        This is the exact scenario the user hit."""
        import textwrap
        setup_git = tmp_path / "target"
        setup_git.mkdir()
        monkeypatch.setenv("ROMYQ_WORKSPACE", "")
        monkeypatch.setenv("GIT_AUTHOR_NAME", "Test")
        monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@test.com")
        monkeypatch.setenv("GIT_COMMITTER_NAME", "Test")
        monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@test.com")

        code = textwrap.dedent(f"""\
        import os, sys
        sys.path.insert(0, {str(Path(__file__).resolve().parent.parent)!r})
        os.chdir({str(setup_git)!r})
        os.rmdir({str(setup_git)!r})

        from romyq.cli import cmd_init

        class Args:
            workspace = None
            no_vcs = False
            no_wizard = True

        try:
            cmd_init(Args())
            print("PASS")
        except Exception as e:
            print(f"FAIL: {{type(e).__name__}}: {{e}}")
            sys.exit(1)
        """)
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, f"Subprocess failed: {result.stderr}"
