"""Tests for romyq.capabilities — project capability model."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq import capabilities as cap_mod


@pytest.fixture()
def ps_file(tmp_path):
    return str(tmp_path / "project_state.json")


@pytest.fixture()
def history_file(tmp_path):
    return str(tmp_path / "history.json")


def _write_history(path: str, entries: list[dict]) -> None:
    Path(path).write_text(json.dumps(entries), encoding="utf-8")


def _entry(task: str, success: bool = True) -> dict:
    return {
        "task": task,
        "success": success,
        "validation_reason": "ok" if success else "fail",
        "timestamp": "2025-01-01T00:00:00+00:00",
        "mode": "impl",
        "commit": "",
    }


# ── TestLoad ──────────────────────────────────────────────────────────────────

class TestLoad:
    def test_empty_on_missing_file(self, ps_file):
        data = cap_mod.load(ps_file)
        assert data == {"version": 1, "generated_at": "", "capabilities": []}

    def test_empty_on_corrupt_file(self, ps_file):
        Path(ps_file).write_text("{invalid json", encoding="utf-8")
        data = cap_mod.load(ps_file)
        assert data["capabilities"] == []

    def test_loads_existing(self, ps_file):
        cap_mod.set_capability(ps_file, "Testing", "partial")
        data = cap_mod.load(ps_file)
        assert len(data["capabilities"]) == 1
        assert data["capabilities"][0]["name"] == "Testing"

    def test_defaults_version(self, ps_file):
        Path(ps_file).parent.mkdir(parents=True, exist_ok=True)
        Path(ps_file).write_text(json.dumps({"capabilities": []}), encoding="utf-8")
        data = cap_mod.load(ps_file)
        assert data["version"] == 1


# ── TestSetCapability ─────────────────────────────────────────────────────────

class TestSetCapability:
    def test_creates_new_capability(self, ps_file):
        cap_mod.set_capability(ps_file, "Testing", "partial")
        caps = cap_mod.list_capabilities(ps_file)
        assert len(caps) == 1
        assert caps[0]["name"] == "Testing"
        assert caps[0]["status"] == "partial"

    def test_updates_existing(self, ps_file):
        cap_mod.set_capability(ps_file, "Testing", "partial")
        cap_mod.set_capability(ps_file, "Testing", "complete")
        caps = cap_mod.list_capabilities(ps_file)
        assert len(caps) == 1
        assert caps[0]["status"] == "complete"

    def test_case_insensitive_update(self, ps_file):
        cap_mod.set_capability(ps_file, "testing", "partial")
        cap_mod.set_capability(ps_file, "Testing", "complete")
        caps = cap_mod.list_capabilities(ps_file)
        assert len(caps) == 1
        assert caps[0]["status"] == "complete"

    def test_adds_evidence(self, ps_file):
        cap_mod.set_capability(ps_file, "Auth", "partial", "Implemented JWT login")
        cap = cap_mod.get_capability(ps_file, "Auth")
        assert cap is not None
        assert "Implemented JWT login" in cap["evidence"]

    def test_evidence_capped_at_five(self, ps_file):
        cap_mod.set_capability(ps_file, "Auth", "partial", "e1")
        for i in range(7):
            cap_mod.set_capability(ps_file, "Auth", "partial", f"evidence {i}")
        cap = cap_mod.get_capability(ps_file, "Auth")
        assert len(cap["evidence"]) <= 5

    def test_invalid_status_raises(self, ps_file):
        with pytest.raises(ValueError, match="Invalid status"):
            cap_mod.set_capability(ps_file, "Testing", "unknown_status")

    def test_empty_name_raises(self, ps_file):
        with pytest.raises(ValueError, match="cannot be empty"):
            cap_mod.set_capability(ps_file, "  ", "complete")

    def test_multiple_capabilities(self, ps_file):
        cap_mod.set_capability(ps_file, "Authentication", "complete")
        cap_mod.set_capability(ps_file, "Testing", "partial")
        cap_mod.set_capability(ps_file, "Deployment", "missing")
        caps = cap_mod.list_capabilities(ps_file)
        assert len(caps) == 3

    def test_uses_atomic_write(self, ps_file, tmp_path):
        cap_mod.set_capability(ps_file, "Auth", "complete")
        assert Path(ps_file).exists()
        assert not list(tmp_path.glob("*.tmp"))


# ── TestGetCapability ─────────────────────────────────────────────────────────

class TestGetCapability:
    def test_returns_none_for_missing(self, ps_file):
        result = cap_mod.get_capability(ps_file, "NonExistent")
        assert result is None

    def test_returns_dict_for_existing(self, ps_file):
        cap_mod.set_capability(ps_file, "Testing", "complete")
        result = cap_mod.get_capability(ps_file, "Testing")
        assert result is not None
        assert result["status"] == "complete"

    def test_case_insensitive_lookup(self, ps_file):
        cap_mod.set_capability(ps_file, "Testing", "partial")
        result = cap_mod.get_capability(ps_file, "TESTING")
        assert result is not None


# ── TestCapabilitySummary ─────────────────────────────────────────────────────

class TestCapabilitySummary:
    def test_empty(self, ps_file):
        s = cap_mod.capability_summary(ps_file)
        assert s["total"] == 0
        assert s["complete"] == 0

    def test_counts(self, ps_file):
        cap_mod.set_capability(ps_file, "Auth", "complete")
        cap_mod.set_capability(ps_file, "Testing", "partial")
        cap_mod.set_capability(ps_file, "Deploy", "missing")
        s = cap_mod.capability_summary(ps_file)
        assert s["total"] == 3
        assert s["complete"] == 1
        assert s["partial"] == 1
        assert s["missing"] == 1


# ── TestInferCapabilityFromTask ───────────────────────────────────────────────

class TestInferCapabilityFromTask:
    def test_auth_task(self):
        result = cap_mod.infer_capability_from_task("Implement JWT authentication")
        assert result == "Authentication"

    def test_test_task(self):
        result = cap_mod.infer_capability_from_task("Write pytest tests for user service")
        assert result == "Testing"

    def test_database_task(self):
        result = cap_mod.infer_capability_from_task("Run database migration for user table")
        assert result == "Database"

    def test_security_task(self):
        result = cap_mod.infer_capability_from_task("Add CSRF and XSS protection")
        assert result == "Security"

    def test_deployment_task(self):
        result = cap_mod.infer_capability_from_task("Create Dockerfile for deployment")
        assert result == "Deployment"

    def test_unknown_task_returns_empty(self):
        result = cap_mod.infer_capability_from_task("Do a random unrelated thing")
        assert result == ""

    def test_empty_task(self):
        result = cap_mod.infer_capability_from_task("")
        assert result == ""


# ── TestInferFromHistory ──────────────────────────────────────────────────────

class TestInferFromHistory:
    def test_no_op_on_empty_history(self, ps_file, history_file):
        _write_history(history_file, [])
        cap_mod.infer_from_history(ps_file, history_file)
        caps = cap_mod.list_capabilities(ps_file)
        assert caps == []

    def test_partial_on_single_success(self, ps_file, history_file):
        _write_history(history_file, [_entry("Write pytest tests for login")])
        cap_mod.infer_from_history(ps_file, history_file)
        cap = cap_mod.get_capability(ps_file, "Testing")
        assert cap is not None
        assert cap["status"] == "partial"

    def test_complete_on_two_successes(self, ps_file, history_file):
        _write_history(history_file, [
            _entry("Write pytest tests for login"),
            _entry("Add unittest coverage for user service"),
        ])
        cap_mod.infer_from_history(ps_file, history_file)
        cap = cap_mod.get_capability(ps_file, "Testing")
        assert cap is not None
        assert cap["status"] == "complete"

    def test_missing_cap_not_added_when_no_match(self, ps_file, history_file):
        _write_history(history_file, [_entry("Fix some random issue")])
        cap_mod.infer_from_history(ps_file, history_file)
        # "Core Features" may be added if 'api' appears, but not other caps
        caps = cap_mod.list_capabilities(ps_file)
        names = {c["name"] for c in caps}
        assert "Authentication" not in names

    def test_failures_do_not_promote_to_complete(self, ps_file, history_file):
        _write_history(history_file, [
            _entry("Write pytest tests", success=False),
            _entry("Write pytest tests again", success=False),
        ])
        cap_mod.infer_from_history(ps_file, history_file)
        cap = cap_mod.get_capability(ps_file, "Testing")
        assert cap is None  # not added at all when no successes

    def test_no_op_on_missing_history_file(self, ps_file, tmp_path):
        cap_mod.infer_from_history(ps_file, str(tmp_path / "nonexistent.json"))
        assert cap_mod.list_capabilities(ps_file) == []


# ── TestFormatCapabilities ────────────────────────────────────────────────────

class TestFormatCapabilities:
    def test_empty_message(self, ps_file):
        result = cap_mod.format_capabilities(ps_file)
        assert "(no capabilities" in result

    def test_shows_capability_name(self, ps_file):
        cap_mod.set_capability(ps_file, "Testing", "complete")
        result = cap_mod.format_capabilities(ps_file)
        assert "Testing" in result

    def test_shows_status_icon(self, ps_file):
        cap_mod.set_capability(ps_file, "Testing", "complete")
        result = cap_mod.format_capabilities(ps_file)
        assert "✓" in result

    def test_partial_icon(self, ps_file):
        cap_mod.set_capability(ps_file, "Auth", "partial")
        result = cap_mod.format_capabilities(ps_file)
        assert "~" in result

    def test_missing_icon(self, ps_file):
        cap_mod.set_capability(ps_file, "Deploy", "missing")
        result = cap_mod.format_capabilities(ps_file)
        assert "✗" in result


# ── TestConstants ─────────────────────────────────────────────────────────────

class TestConstants:
    def test_statuses_frozenset(self):
        assert "complete" in cap_mod.CAPABILITY_STATUSES
        assert "partial" in cap_mod.CAPABILITY_STATUSES
        assert "missing" in cap_mod.CAPABILITY_STATUSES

    def test_standard_capabilities_list(self):
        assert "Authentication" in cap_mod.STANDARD_CAPABILITIES
        assert "Testing" in cap_mod.STANDARD_CAPABILITIES
        assert len(cap_mod.STANDARD_CAPABILITIES) == 12

    def test_status_icons(self):
        assert cap_mod.STATUS_ICONS["complete"] == "✓"
        assert cap_mod.STATUS_ICONS["partial"] == "~"
        assert cap_mod.STATUS_ICONS["missing"] == "✗"

    def test_status_scores(self):
        assert cap_mod.STATUS_SCORES["complete"] == 100
        assert cap_mod.STATUS_SCORES["partial"] == 50
        assert cap_mod.STATUS_SCORES["missing"] == 0
