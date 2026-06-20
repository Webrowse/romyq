"""Complexity profile — determines project depth, testing requirements, readiness thresholds.

.romyq/project_profile.json structure:
{
  "version": 1,
  "complexity": "intermediate",
  "set_at": "2026-01-01T00:00:00+00:00"
}
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone

_VERSION = 1
VALID_LEVELS = frozenset({"basic", "intermediate", "advanced"})

COMPLEXITY_CONFIG: dict[str, dict] = {
    "basic": {
        "label": "Basic",
        "description": "MVP — minimal architecture, stop when software works",
        "readiness_target": 60,
        "done_criteria": ["software runs"],
        "min_phases": 2,
        "security_required": False,
        "docs_required": False,
        "ci_required": False,
        "deployment_required": False,
        "testing_required": False,
    },
    "intermediate": {
        "label": "Intermediate",
        "description": "Proper architecture, tests, docs, CI",
        "readiness_target": 75,
        "done_criteria": ["software runs", "tests pass", "README exists"],
        "min_phases": 3,
        "security_required": False,
        "docs_required": True,
        "ci_required": True,
        "deployment_required": False,
        "testing_required": True,
    },
    "advanced": {
        "label": "Advanced",
        "description": "Production-grade: security, CI/CD, monitoring, docs, deployment",
        "readiness_target": 90,
        "done_criteria": [
            "software runs",
            "tests pass",
            "CI passes",
            "docs complete",
            "deployment ready",
            "security requirements met",
        ],
        "min_phases": 5,
        "security_required": True,
        "docs_required": True,
        "ci_required": True,
        "deployment_required": True,
        "testing_required": True,
    },
}


def _empty() -> dict:
    return {
        "version": _VERSION,
        "complexity": "intermediate",
        "set_at": "",
    }


def load(profile_path: str) -> dict:
    """Load project_profile.json, returning defaults on missing or corrupt file."""
    try:
        with open(profile_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        if data.get("complexity") not in VALID_LEVELS:
            data["complexity"] = "intermediate"
        data.setdefault("version", _VERSION)
        data.setdefault("set_at", "")
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty()


def _write_atomic(profile_path: str, data: dict) -> None:
    dir_ = os.path.dirname(os.path.abspath(profile_path))
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, profile_path)


def set_complexity(profile_path: str, level: str) -> None:
    """Set the complexity level and persist to disk."""
    if level not in VALID_LEVELS:
        raise ValueError(f"complexity must be one of {sorted(VALID_LEVELS)}, got {level!r}")
    data = load(profile_path)
    data["complexity"] = level
    data["set_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _write_atomic(profile_path, data)


def get_complexity(profile_path: str) -> str:
    """Return the stored complexity level (defaults to 'intermediate')."""
    return load(profile_path).get("complexity", "intermediate")


def config(level: str) -> dict:
    """Return the configuration dict for a complexity level.

    Falls back to 'intermediate' if level is unrecognised.
    """
    if level not in COMPLEXITY_CONFIG:
        level = "intermediate"
    return dict(COMPLEXITY_CONFIG[level])


def readiness_target(profile_path: str) -> int:
    """Return the readiness % target for the current complexity."""
    level = get_complexity(profile_path)
    return COMPLEXITY_CONFIG.get(level, COMPLEXITY_CONFIG["intermediate"])["readiness_target"]


def done_criteria(profile_path: str) -> list[str]:
    """Return the done criteria list for the current complexity."""
    level = get_complexity(profile_path)
    return list(COMPLEXITY_CONFIG.get(level, COMPLEXITY_CONFIG["intermediate"])["done_criteria"])


def format_profile(profile_path: str) -> str:
    """Return a human-readable summary of the current complexity profile."""
    data = load(profile_path)
    level = data.get("complexity", "intermediate")
    cfg = COMPLEXITY_CONFIG.get(level, COMPLEXITY_CONFIG["intermediate"])
    lines = [
        f"Complexity   : {cfg['label']}",
        f"Description  : {cfg['description']}",
        f"Target       : {cfg['readiness_target']}% readiness",
        f"Done criteria: {', '.join(cfg['done_criteria'])}",
    ]
    return "\n".join(lines)
