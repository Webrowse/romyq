"""Tests for romyq.constitution — project constitution generator."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq import constitution as con_mod


@pytest.fixture()
def workspace(tmp_path):
    """Minimal workspace with mission.md."""
    (tmp_path / "mission.md").write_text("Build a REST API for task management.", encoding="utf-8")
    return str(tmp_path)


@pytest.fixture()
def rules_file(tmp_path):
    return str(tmp_path / ".romyq" / "rules.json")


@pytest.fixture()
def knowledge_file(tmp_path):
    path = tmp_path / ".romyq" / "knowledge.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@pytest.fixture()
def ps_file(tmp_path):
    path = tmp_path / ".romyq" / "project_state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


@pytest.fixture()
def events_file(tmp_path):
    path = tmp_path / ".romyq" / "events.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    return str(path)


# ── TestGenerate ──────────────────────────────────────────────────────────────

class TestGenerate:
    def test_returns_string(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(
            workspace,
            rules_path=rules_file,
            knowledge_path=knowledge_file,
            project_state_path=ps_file,
            events_path=events_file,
        )
        assert isinstance(result, str)

    def test_contains_mission_section(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "## Mission" in result

    def test_contains_mission_content(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "REST API" in result

    def test_contains_rules_section(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "## Project Rules" in result

    def test_contains_knowledge_section(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "## Knowledge Lessons" in result

    def test_contains_capabilities_section(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "## Capabilities" in result

    def test_contains_readiness_section(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "## Mission Readiness" in result

    def test_contains_priorities_section(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "## Current Priorities" in result

    def test_sections_separated_by_dashes(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "---" in result

    def test_contains_generated_timestamp(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "Generated" in result

    def test_includes_rules_when_present(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        from romyq.rules import add_rule
        add_rule(rules_file, "Never use SQLite")
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "Never use SQLite" in result

    def test_includes_lessons_from_knowledge(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        data = {"patterns": [{"type": "success_pattern", "lesson": "Always write tests first"}]}
        Path(knowledge_file).write_text(json.dumps(data), encoding="utf-8")
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "Always write tests first" in result

    def test_includes_capabilities_when_set(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        from romyq.capabilities import set_capability
        set_capability(ps_file, "Testing", "complete")
        result = con_mod.generate(workspace, rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "Testing" in result

    def test_missing_mission_graceful(self, tmp_path, rules_file, knowledge_file, ps_file, events_file):
        result = con_mod.generate(str(tmp_path), rules_path=rules_file,
                                  knowledge_path=knowledge_file,
                                  project_state_path=ps_file, events_path=events_file)
        assert "not found" in result or "Mission" in result

    def test_uses_workspace_defaults(self, workspace):
        result = con_mod.generate(workspace)
        assert isinstance(result, str)
        assert "## Mission" in result


# ── TestWrite ─────────────────────────────────────────────────────────────────

class TestWrite:
    def test_creates_file(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        path = con_mod.write(workspace, rules_path=rules_file,
                             knowledge_path=knowledge_file,
                             project_state_path=ps_file, events_path=events_file)
        assert Path(path).exists()

    def test_writes_to_romyq_dir(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        path = con_mod.write(workspace, rules_path=rules_file,
                             knowledge_path=knowledge_file,
                             project_state_path=ps_file, events_path=events_file)
        assert ".romyq" in path
        assert "project.md" in path

    def test_content_is_valid(self, workspace, rules_file, knowledge_file, ps_file, events_file):
        path = con_mod.write(workspace, rules_path=rules_file,
                             knowledge_path=knowledge_file,
                             project_state_path=ps_file, events_path=events_file)
        content = Path(path).read_text(encoding="utf-8")
        assert "## Mission" in content

    def test_uses_atomic_write(self, workspace, rules_file, knowledge_file, ps_file, events_file, tmp_path):
        path = con_mod.write(workspace, rules_path=rules_file,
                             knowledge_path=knowledge_file,
                             project_state_path=ps_file, events_path=events_file)
        romyq_dir = Path(path).parent
        assert not list(romyq_dir.glob("*.tmp"))

    def test_returns_path_string(self, workspace):
        path = con_mod.write(workspace)
        assert isinstance(path, str)
        assert path.endswith("project.md")
