"""Tests for the enhanced romyq version command (Finding R3).

Verifies that romyq version shows:
  - version string
  - install type
  - python version
  - executable path
  - venv path or "none" + warning
"""
from __future__ import annotations

import argparse
import os
import sys
from unittest.mock import patch

import pytest

from romyq.cli import cmd_version


def _run(capsys, *, virtual_env: str = "", prefix: str = "", base_prefix: str = ""):
    """Run cmd_version with the given environment overrides and return stdout."""
    ns = argparse.Namespace()
    env_patch = {**os.environ}
    if virtual_env:
        env_patch["VIRTUAL_ENV"] = virtual_env
    else:
        env_patch.pop("VIRTUAL_ENV", None)

    with patch.dict(os.environ, env_patch, clear=True), \
         patch.object(sys, "prefix", prefix or sys.prefix), \
         patch.object(sys, "base_prefix", base_prefix or sys.prefix):
        cmd_version(ns)

    return capsys.readouterr().out


class TestVersionCmdOutput:

    def test_shows_version(self, capsys):
        cmd_version(argparse.Namespace())
        out = capsys.readouterr().out
        assert "romyq" in out

    def test_shows_install_line(self, capsys):
        cmd_version(argparse.Namespace())
        out = capsys.readouterr().out
        assert "install" in out

    def test_shows_python_line(self, capsys):
        cmd_version(argparse.Namespace())
        out = capsys.readouterr().out
        assert "python" in out
        assert sys.version.split()[0] in out

    def test_shows_executable_line(self, capsys):
        cmd_version(argparse.Namespace())
        out = capsys.readouterr().out
        assert "executable" in out

    def test_executable_path_is_absolute(self, capsys):
        cmd_version(argparse.Namespace())
        out = capsys.readouterr().out
        for line in out.splitlines():
            if "executable" in line:
                # Everything after the label
                parts = line.strip().split(None, 1)
                if len(parts) == 2:
                    assert os.path.isabs(parts[1].strip()), \
                        f"Executable path is not absolute: {parts[1]}"
                break

    def test_shows_venv_line(self, capsys):
        cmd_version(argparse.Namespace())
        out = capsys.readouterr().out
        assert "venv" in out


class TestVenvDetection:

    def test_virtual_env_var_shown_when_set(self, capsys):
        """When VIRTUAL_ENV is set, its value appears in the venv line."""
        ns = argparse.Namespace()
        with patch.dict(os.environ, {"VIRTUAL_ENV": "/tmp/my-venv"}, clear=False):
            cmd_version(ns)
        out = capsys.readouterr().out
        assert "/tmp/my-venv" in out
        assert "Warning" not in out

    def test_no_warning_inside_venv(self, capsys):
        """No warning is printed when running inside a venv."""
        ns = argparse.Namespace()
        with patch.dict(os.environ, {"VIRTUAL_ENV": "/tmp/my-venv"}, clear=False):
            cmd_version(ns)
        out = capsys.readouterr().out
        assert "Warning" not in out

    def test_warning_outside_venv(self, capsys):
        """Warning is printed when not running inside any venv."""
        ns = argparse.Namespace()
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(sys, "prefix", "/usr"), \
             patch.object(sys, "base_prefix", "/usr"):
            if hasattr(sys, "real_prefix"):
                with patch.object(sys, "real_prefix", None, create=False):
                    cmd_version(ns)
            else:
                cmd_version(ns)
        out = capsys.readouterr().out
        assert "Warning" in out
        assert "virtual environment" in out

    def test_venv_none_outside_venv(self, capsys):
        """venv line shows 'none' when not in a venv."""
        ns = argparse.Namespace()
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(sys, "prefix", "/usr"), \
             patch.object(sys, "base_prefix", "/usr"):
            cmd_version(ns)
        out = capsys.readouterr().out
        for line in out.splitlines():
            if "venv" in line and "executable" not in line:
                assert "none" in line
                break

    def test_venv_shown_when_prefix_differs(self, capsys):
        """When sys.prefix != sys.base_prefix, venv path is shown."""
        ns = argparse.Namespace()
        env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
        with patch.dict(os.environ, env, clear=True), \
             patch.object(sys, "prefix", "/home/user/project/.venv"), \
             patch.object(sys, "base_prefix", "/usr"):
            cmd_version(ns)
        out = capsys.readouterr().out
        assert "/home/user/project/.venv" in out
        assert "Warning" not in out
