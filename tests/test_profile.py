"""Tests for romyq.profile — complexity profile persistence and config."""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from romyq.profile import (
    COMPLEXITY_CONFIG,
    VALID_LEVELS,
    _empty,
    config,
    done_criteria,
    format_profile,
    get_complexity,
    load,
    readiness_target,
    set_complexity,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def _profile_file(tmp_path, data=None) -> str:
    p = str(tmp_path / "project_profile.json")
    if data is not None:
        with open(p, "w") as f:
            json.dump(data, f)
    return p


# ── _empty ────────────────────────────────────────────────────────────────────

class TestEmpty:
    def test_default_complexity(self):
        e = _empty()
        assert e["complexity"] == "intermediate"

    def test_version_is_one(self):
        e = _empty()
        assert e["version"] == 1

    def test_set_at_empty(self):
        e = _empty()
        assert e["set_at"] == ""


# ── VALID_LEVELS ──────────────────────────────────────────────────────────────

class TestValidLevels:
    def test_has_three_levels(self):
        assert len(VALID_LEVELS) == 3

    def test_contains_basic(self):
        assert "basic" in VALID_LEVELS

    def test_contains_intermediate(self):
        assert "intermediate" in VALID_LEVELS

    def test_contains_advanced(self):
        assert "advanced" in VALID_LEVELS


# ── COMPLEXITY_CONFIG ─────────────────────────────────────────────────────────

class TestComplexityConfig:
    def test_all_levels_have_readiness_target(self):
        for level in VALID_LEVELS:
            assert "readiness_target" in COMPLEXITY_CONFIG[level]

    def test_basic_readiness_lowest(self):
        assert COMPLEXITY_CONFIG["basic"]["readiness_target"] < COMPLEXITY_CONFIG["intermediate"]["readiness_target"]

    def test_intermediate_readiness_lower_than_advanced(self):
        assert COMPLEXITY_CONFIG["intermediate"]["readiness_target"] < COMPLEXITY_CONFIG["advanced"]["readiness_target"]

    def test_basic_has_one_criterion(self):
        assert len(COMPLEXITY_CONFIG["basic"]["done_criteria"]) == 1

    def test_intermediate_has_multiple_criteria(self):
        assert len(COMPLEXITY_CONFIG["intermediate"]["done_criteria"]) > 1

    def test_advanced_has_most_criteria(self):
        assert len(COMPLEXITY_CONFIG["advanced"]["done_criteria"]) > len(COMPLEXITY_CONFIG["intermediate"]["done_criteria"])

    def test_basic_security_not_required(self):
        assert not COMPLEXITY_CONFIG["basic"]["security_required"]

    def test_advanced_security_required(self):
        assert COMPLEXITY_CONFIG["advanced"]["security_required"]

    def test_basic_docs_not_required(self):
        assert not COMPLEXITY_CONFIG["basic"]["docs_required"]

    def test_intermediate_docs_required(self):
        assert COMPLEXITY_CONFIG["intermediate"]["docs_required"]


# ── load ──────────────────────────────────────────────────────────────────────

class TestLoad:
    def test_missing_file_returns_default(self, tmp_path):
        p = str(tmp_path / "nonexistent.json")
        data = load(p)
        assert data["complexity"] == "intermediate"

    def test_corrupt_file_returns_default(self, tmp_path):
        p = str(tmp_path / "profile.json")
        with open(p, "w") as f:
            f.write("not json {{{")
        data = load(p)
        assert data["complexity"] == "intermediate"

    def test_invalid_complexity_defaults_to_intermediate(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "ultra"})
        data = load(p)
        assert data["complexity"] == "intermediate"

    def test_loads_valid_file(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "basic", "version": 1, "set_at": ""})
        data = load(p)
        assert data["complexity"] == "basic"

    def test_non_dict_returns_default(self, tmp_path):
        p = _profile_file(tmp_path, [1, 2, 3])
        data = load(p)
        assert data["complexity"] == "intermediate"

    def test_sets_defaults_for_missing_keys(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "advanced"})
        data = load(p)
        assert "version" in data
        assert "set_at" in data


# ── set_complexity ────────────────────────────────────────────────────────────

class TestSetComplexity:
    def test_set_basic(self, tmp_path):
        p = _profile_file(tmp_path)
        set_complexity(p, "basic")
        assert get_complexity(p) == "basic"

    def test_set_intermediate(self, tmp_path):
        p = _profile_file(tmp_path)
        set_complexity(p, "intermediate")
        assert get_complexity(p) == "intermediate"

    def test_set_advanced(self, tmp_path):
        p = _profile_file(tmp_path)
        set_complexity(p, "advanced")
        assert get_complexity(p) == "advanced"

    def test_invalid_level_raises(self, tmp_path):
        p = _profile_file(tmp_path)
        with pytest.raises(ValueError):
            set_complexity(p, "elite")

    def test_sets_timestamp(self, tmp_path):
        p = _profile_file(tmp_path)
        set_complexity(p, "basic")
        data = load(p)
        assert data["set_at"] != ""

    def test_overwrites_previous(self, tmp_path):
        p = _profile_file(tmp_path)
        set_complexity(p, "basic")
        set_complexity(p, "advanced")
        assert get_complexity(p) == "advanced"

    def test_creates_file_if_missing(self, tmp_path):
        p = str(tmp_path / "new_profile.json")
        set_complexity(p, "basic")
        assert os.path.exists(p)


# ── get_complexity ────────────────────────────────────────────────────────────

class TestGetComplexity:
    def test_default_is_intermediate(self, tmp_path):
        p = str(tmp_path / "nonexistent.json")
        assert get_complexity(p) == "intermediate"

    def test_returns_stored_value(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "advanced", "version": 1, "set_at": ""})
        assert get_complexity(p) == "advanced"


# ── config ────────────────────────────────────────────────────────────────────

class TestConfig:
    def test_returns_dict(self):
        c = config("basic")
        assert isinstance(c, dict)

    def test_unknown_falls_back_to_intermediate(self):
        c = config("unknown_level")
        c_i = config("intermediate")
        assert c["readiness_target"] == c_i["readiness_target"]

    def test_returns_copy(self):
        c1 = config("basic")
        c2 = config("basic")
        c1["label"] = "MUTATED"
        assert c2["label"] != "MUTATED"

    def test_all_required_keys_present(self):
        required = {"label", "description", "readiness_target", "done_criteria",
                    "min_phases", "security_required", "docs_required",
                    "ci_required", "deployment_required", "testing_required"}
        for level in VALID_LEVELS:
            c = config(level)
            assert required <= set(c.keys()), f"Missing keys in {level}: {required - set(c.keys())}"


# ── readiness_target ──────────────────────────────────────────────────────────

class TestReadinessTarget:
    def test_basic_returns_60(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "basic", "version": 1, "set_at": ""})
        assert readiness_target(p) == 60

    def test_intermediate_returns_75(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "intermediate", "version": 1, "set_at": ""})
        assert readiness_target(p) == 75

    def test_advanced_returns_90(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "advanced", "version": 1, "set_at": ""})
        assert readiness_target(p) == 90

    def test_missing_file_defaults_to_intermediate(self, tmp_path):
        p = str(tmp_path / "none.json")
        assert readiness_target(p) == 75


# ── done_criteria ─────────────────────────────────────────────────────────────

class TestDoneCriteria:
    def test_basic_returns_list(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "basic", "version": 1, "set_at": ""})
        crit = done_criteria(p)
        assert isinstance(crit, list)
        assert len(crit) >= 1

    def test_basic_has_software_runs(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "basic", "version": 1, "set_at": ""})
        crit = done_criteria(p)
        assert any("software" in c.lower() for c in crit)

    def test_advanced_has_more_criteria(self, tmp_path):
        os.makedirs(str(tmp_path / "b"), exist_ok=True)
        p_b = str(tmp_path / "b" / "p.json")
        with open(p_b, "w") as f:
            json.dump({"complexity": "basic", "version": 1, "set_at": ""}, f)

        p_a = str(tmp_path / "a.json")
        with open(p_a, "w") as f:
            json.dump({"complexity": "advanced", "version": 1, "set_at": ""}, f)

        assert len(done_criteria(p_a)) > len(done_criteria(p_b))

    def test_returns_copy(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "intermediate", "version": 1, "set_at": ""})
        crit = done_criteria(p)
        crit.append("extra")
        crit2 = done_criteria(p)
        assert "extra" not in crit2


# ── format_profile ────────────────────────────────────────────────────────────

class TestFormatProfile:
    def test_returns_string(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "intermediate", "version": 1, "set_at": ""})
        result = format_profile(p)
        assert isinstance(result, str)

    def test_contains_complexity_level(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "advanced", "version": 1, "set_at": ""})
        result = format_profile(p)
        assert "Advanced" in result

    def test_contains_readiness_target(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "advanced", "version": 1, "set_at": ""})
        result = format_profile(p)
        assert "90" in result

    def test_contains_done_criteria(self, tmp_path):
        p = _profile_file(tmp_path, {"complexity": "basic", "version": 1, "set_at": ""})
        result = format_profile(p)
        assert "software runs" in result.lower()
