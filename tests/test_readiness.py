"""Tests for romyq.readiness — mission readiness scoring."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from romyq import readiness as rd_mod


@pytest.fixture()
def ps_file(tmp_path):
    return str(tmp_path / "project_state.json")


def _make_caps(specs: list[tuple[str, str]]) -> list[dict]:
    """Build capability list from (name, status) tuples."""
    return [{"name": name, "status": status, "evidence": [], "added_at": "", "updated_at": ""} for name, status in specs]


# ── TestCompute ───────────────────────────────────────────────────────────────

class TestCompute:
    def test_returns_dict(self):
        result = rd_mod.compute([])
        assert isinstance(result, dict)

    def test_has_required_keys(self):
        result = rd_mod.compute([])
        assert "overall" in result
        assert "label" in result
        assert "categories" in result

    def test_zero_overall_when_no_caps(self):
        result = rd_mod.compute([])
        assert result["overall"] == 0.0

    def test_four_categories_present(self):
        result = rd_mod.compute([])
        assert set(result["categories"]) == {
            "Core Functionality", "Testing", "Security", "Operations"
        }

    def test_100_when_all_complete(self):
        caps = _make_caps([
            ("Core Features", "complete"),
            ("Database", "complete"),
            ("Validation", "complete"),
            ("Testing", "complete"),
            ("Security", "complete"),
            ("Authentication", "complete"),
            ("Authorization", "complete"),
            ("Deployment", "complete"),
            ("Observability", "complete"),
            ("Documentation", "complete"),
        ])
        result = rd_mod.compute(caps)
        assert result["overall"] == pytest.approx(100.0)

    def test_partial_score_with_partial_caps(self):
        caps = _make_caps([("Testing", "partial")])
        result = rd_mod.compute(caps)
        # Testing is 25% weight and partial = 50 → 0.25 * 50 = 12.5
        assert 0 < result["overall"] < 100

    def test_category_score_is_0_to_100(self):
        caps = _make_caps([("Testing", "complete")])
        result = rd_mod.compute(caps)
        for cat_info in result["categories"].values():
            assert 0 <= cat_info["score"] <= 100

    def test_testing_category_uses_testing_cap(self):
        caps_complete = _make_caps([("Testing", "complete")])
        caps_missing = _make_caps([("Testing", "missing")])
        r_complete = rd_mod.compute(caps_complete)
        r_missing = rd_mod.compute(caps_missing)
        assert r_complete["categories"]["Testing"]["score"] > r_missing["categories"]["Testing"]["score"]

    def test_core_functionality_uses_right_caps(self):
        caps = _make_caps([
            ("Core Features", "complete"),
            ("Database", "complete"),
            ("Validation", "complete"),
        ])
        result = rd_mod.compute(caps)
        assert result["categories"]["Core Functionality"]["score"] == pytest.approx(100.0)

    def test_security_category_uses_auth_caps(self):
        caps = _make_caps([
            ("Authentication", "complete"),
            ("Authorization", "complete"),
            ("Security", "complete"),
        ])
        result = rd_mod.compute(caps)
        assert result["categories"]["Security"]["score"] == pytest.approx(100.0)

    def test_statuses_in_category(self):
        caps = _make_caps([("Testing", "partial")])
        result = rd_mod.compute(caps)
        statuses = result["categories"]["Testing"]["statuses"]
        assert "Testing" in statuses
        assert statuses["Testing"] == "partial"

    def test_required_list_in_category(self):
        result = rd_mod.compute([])
        assert "required" in result["categories"]["Testing"]
        assert "Testing" in result["categories"]["Testing"]["required"]


# ── TestLabel ─────────────────────────────────────────────────────────────────

class TestLabel:
    def test_not_ready_below_50(self):
        caps = []
        result = rd_mod.compute(caps)
        assert result["label"] == "Not Ready"

    def test_approaching_at_50(self):
        assert rd_mod._label(50) == "Approaching"

    def test_ready_at_80(self):
        assert rd_mod._label(80) == "Ready"

    def test_excellent_at_90(self):
        assert rd_mod._label(90) == "Excellent"
        assert rd_mod._label(100) == "Excellent"

    def test_not_ready_below_50_label(self):
        assert rd_mod._label(0) == "Not Ready"
        assert rd_mod._label(49) == "Not Ready"

    def test_approaching_range(self):
        assert rd_mod._label(50) == "Approaching"
        assert rd_mod._label(79) == "Approaching"

    def test_ready_range(self):
        assert rd_mod._label(80) == "Ready"
        assert rd_mod._label(89) == "Ready"


# ── TestComputeFromPath ───────────────────────────────────────────────────────

class TestComputeFromPath:
    def test_empty_file(self, ps_file):
        result = rd_mod.compute_from_path(ps_file)
        assert result["overall"] == 0.0

    def test_loads_capabilities(self, ps_file):
        from romyq.capabilities import set_capability
        set_capability(ps_file, "Testing", "complete")
        result = rd_mod.compute_from_path(ps_file)
        assert result["categories"]["Testing"]["score"] == pytest.approx(100.0)

    def test_returns_all_four_categories(self, ps_file):
        result = rd_mod.compute_from_path(ps_file)
        assert len(result["categories"]) == 4


# ── TestFormatReadiness ────────────────────────────────────────────────────────

class TestFormatReadiness:
    def test_returns_string(self):
        result = rd_mod.format_readiness(rd_mod.compute([]))
        assert isinstance(result, str)

    def test_contains_overall(self):
        result = rd_mod.format_readiness(rd_mod.compute([]))
        assert "0%" in result or "Readiness" in result

    def test_contains_all_categories(self):
        result = rd_mod.format_readiness(rd_mod.compute([]))
        assert "Core Functionality" in result
        assert "Testing" in result
        assert "Security" in result
        assert "Operations" in result

    def test_contains_label(self):
        result = rd_mod.format_readiness(rd_mod.compute([]))
        assert "Not Ready" in result


# ── TestWeights ───────────────────────────────────────────────────────────────

class TestWeights:
    def test_weights_sum_to_one(self):
        from romyq.readiness import _CATEGORY_WEIGHTS
        total = sum(_CATEGORY_WEIGHTS.values())
        assert total == pytest.approx(1.0)

    def test_four_weights(self):
        from romyq.readiness import _CATEGORY_WEIGHTS
        assert len(_CATEGORY_WEIGHTS) == 4

    def test_core_functionality_highest_weight(self):
        from romyq.readiness import _CATEGORY_WEIGHTS
        core_weight = _CATEGORY_WEIGHTS["Core Functionality"]
        assert all(core_weight >= w for w in _CATEGORY_WEIGHTS.values())
