"""Project capability model — tracks high-level capabilities, not tasks.

Persisted in .romyq/project_state.json. Capabilities are inferred from
task history and can be manually overridden.

Statuses: missing | partial | complete
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

_VERSION = 1
CAPABILITY_STATUSES = frozenset({"missing", "partial", "complete"})
STATUS_ICONS = {"complete": "✓", "partial": "~", "missing": "✗"}
STATUS_SCORES = {"complete": 100, "partial": 50, "missing": 0}

STANDARD_CAPABILITIES = [
    "Core Features",
    "Authentication",
    "Authorization",
    "Validation",
    "Database",
    "Search",
    "Testing",
    "Documentation",
    "Security",
    "Observability",
    "Deployment",
    "Performance",
]

# Keywords used to match capabilities from task/commit text
_CAPABILITY_KEYWORDS: dict[str, list[str]] = {
    "Authentication": ["auth", "login", "logout", "jwt", "token", "session", "password", "oauth"],
    "Authorization": ["permission", "role", "rbac", "access control", "authorize"],
    "Database": ["database", "migration", "schema", "orm", "sql", "postgres", "sqlite", "mysql", "mongo"],
    "Testing": ["test", "spec", "pytest", "unittest", "coverage", "fixture", "mock"],
    "Validation": ["validate", "validation", "sanitize", "pydantic"],
    "Search": ["search", "fulltext", "elasticsearch", "solr"],
    "Documentation": ["docs", "documentation", "readme", "docstring", "openapi", "swagger"],
    "Security": ["security", "ssl", "https", "csrf", "xss", "cors", "encrypt", "hash"],
    "Observability": ["monitor", "metric", "trace", "health check", "alert", "logging"],
    "Deployment": ["deploy", "dockerfile", "docker", "kubernetes", "ci/cd", "release", "pipeline"],
    "Performance": ["cache", "optimize", "benchmark", "latency", "throughput", "queue"],
    "Core Features": ["endpoint", "route", "controller", "api"],
}


# ── persistence ───────────────────────────────────────────────────────────────

def _empty() -> dict:
    return {
        "version": _VERSION,
        "generated_at": "",
        "capabilities": [],
    }


def _ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(project_state_path: str) -> dict:
    """Load project_state.json, returning empty structure on missing/corrupt."""
    try:
        with open(project_state_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("version", _VERSION)
        data.setdefault("generated_at", "")
        data.setdefault("capabilities", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty()


def _write(project_state_path: str, data: dict) -> str:
    dir_ = os.path.dirname(os.path.abspath(project_state_path))
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, project_state_path)
    return project_state_path


# ── capability matching ───────────────────────────────────────────────────────

def infer_capability_from_task(task: str) -> str:
    """Return the best-matching capability name for a given task, or ''."""
    task_lower = task.lower()
    best = ""
    best_count = 0
    for cap, keywords in _CAPABILITY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in task_lower)
        if count > best_count:
            best_count = count
            best = cap
    return best if best_count > 0 else ""


# ── CRUD ──────────────────────────────────────────────────────────────────────

def set_capability(
    project_state_path: str,
    name: str,
    status: str,
    evidence: str = "",
) -> None:
    """Set or update a capability status. Creates the capability if absent."""
    if status not in CAPABILITY_STATUSES:
        raise ValueError(f"Invalid status: {status!r}. Must be one of {sorted(CAPABILITY_STATUSES)}")
    name = name.strip()
    if not name:
        raise ValueError("Capability name cannot be empty.")
    data = load(project_state_path)
    now = _ts()
    for cap in data["capabilities"]:
        if cap.get("name", "").lower() == name.lower():
            cap["status"] = status
            cap["updated_at"] = now
            if evidence:
                cap.setdefault("evidence", [])
                cap["evidence"].append(evidence[:120])
                cap["evidence"] = cap["evidence"][-5:]  # keep last 5
            _write(project_state_path, data)
            return
    # New capability
    entry: dict = {
        "name": name,
        "status": status,
        "evidence": [evidence[:120]] if evidence else [],
        "added_at": now,
        "updated_at": now,
    }
    data["capabilities"].append(entry)
    data["generated_at"] = now
    _write(project_state_path, data)


def get_capability(project_state_path: str, name: str) -> dict | None:
    """Return a capability dict by name, or None if not found."""
    data = load(project_state_path)
    name_lower = name.lower()
    for cap in data.get("capabilities", []):
        if cap.get("name", "").lower() == name_lower:
            return cap
    return None


def list_capabilities(project_state_path: str) -> list[dict]:
    """Return all capabilities in insertion order."""
    return load(project_state_path).get("capabilities", [])


def capability_summary(project_state_path: str) -> dict:
    """Return counts by status: {total, complete, partial, missing}."""
    caps = list_capabilities(project_state_path)
    counts: dict[str, int] = {s: 0 for s in CAPABILITY_STATUSES}
    for c in caps:
        s = c.get("status", "missing")
        counts[s] = counts.get(s, 0) + 1
    return {"total": len(caps), **counts}


# ── inference from history ────────────────────────────────────────────────────

def infer_from_history(
    project_state_path: str,
    history_path: str,
    limit: int = 100,
) -> None:
    """Infer and update capability statuses from task history.

    A capability moves to:
    - complete: ≥2 successful tasks mention its keywords, success rate ≥ 60%
    - partial:  ≥1 successful task mentions its keywords
    - (missing: not mentioned → not added)
    """
    try:
        from .history import recent
        entries = recent(limit=limit, path=history_path)
    except Exception:
        return

    for cap_name, keywords in _CAPABILITY_KEYWORDS.items():
        relevant = [e for e in entries if any(kw in e.get("task", "").lower() for kw in keywords)]
        if not relevant:
            continue
        successes = sum(1 for e in relevant if e.get("success"))
        total = len(relevant)
        if total == 0:
            continue
        success_rate = successes / total
        if successes >= 2 and success_rate >= 0.6:
            status = "complete"
            evidence = f"{successes}/{total} tasks succeeded"
        elif successes >= 1:
            status = "partial"
            evidence = f"{successes}/{total} tasks succeeded"
        else:
            continue
        try:
            set_capability(project_state_path, cap_name, status, evidence)
        except Exception:
            pass


# ── formatting ────────────────────────────────────────────────────────────────

def format_capabilities(project_state_path: str) -> str:
    """Return a human-readable capability table."""
    caps = list_capabilities(project_state_path)
    if not caps:
        return "(no capabilities tracked yet)"
    lines = []
    width = max(len(c["name"]) for c in caps) + 2
    for c in caps:
        icon = STATUS_ICONS.get(c.get("status", "missing"), "?")
        status_label = c.get("status", "missing").capitalize()
        lines.append(f"  {c['name']:<{width}} {icon} {status_label}")
    return "\n".join(lines)
