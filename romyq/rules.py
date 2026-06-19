"""Project rules — persistent governance constraints for the planner.

Rules are stored in .romyq/rules.json and injected into every DeepSeek
planning call so the planner respects project-wide constraints.

Examples:
  "Always use PostgreSQL"
  "Never use SQLite"
  "Backend first"
  "Require tests for every endpoint"
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

_VERSION = 1
RULE_SOURCES = frozenset({"manual", "promoted"})


# ── persistence ───────────────────────────────────────────────────────────────

def _empty() -> dict:
    return {"version": _VERSION, "rules": []}


def _ts() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load(rules_path: str) -> dict:
    """Load rules.json, returning empty structure on missing or corrupt file."""
    try:
        with open(rules_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("version", _VERSION)
        data.setdefault("rules", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty()


def _write(rules_path: str, data: dict) -> str:
    """Atomically write rules.json. Returns the path."""
    dir_ = os.path.dirname(os.path.abspath(rules_path))
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, rules_path)
    return rules_path


# ── CRUD ──────────────────────────────────────────────────────────────────────

def add_rule(rules_path: str, text: str, source: str = "manual") -> str:
    """Add a new active rule. Returns the new rule ID.

    Silently returns existing ID if the rule text already exists (active).
    """
    text = text.strip()
    if not text:
        raise ValueError("Rule text cannot be empty.")
    if source not in RULE_SOURCES:
        source = "manual"

    data = load(rules_path)
    for rule in data["rules"]:
        if rule.get("text", "").lower() == text.lower() and rule.get("active"):
            return rule["id"]

    rule_id = uuid.uuid4().hex[:8]
    data["rules"].append({
        "id": rule_id,
        "text": text,
        "active": True,
        "created_at": _ts(),
        "source": source,
    })
    _write(rules_path, data)
    return rule_id


def remove_rule(rules_path: str, id_or_text: str) -> bool:
    """Deactivate a rule by ID or exact text. Returns True if found and deactivated."""
    id_or_text = id_or_text.strip()
    if not id_or_text:
        return False
    data = load(rules_path)
    changed = False
    lower = id_or_text.lower()
    for rule in data["rules"]:
        if rule.get("id") == id_or_text or rule.get("text", "").lower() == lower:
            if rule.get("active"):
                rule["active"] = False
                changed = True
                break
    if changed:
        _write(rules_path, data)
    return changed


def list_rules(rules_path: str) -> list[dict]:
    """Return active rules only, in insertion order."""
    data = load(rules_path)
    return [r for r in data.get("rules", []) if r.get("active")]


def all_rules(rules_path: str) -> list[dict]:
    """Return all rules including inactive ones."""
    return load(rules_path).get("rules", [])


# ── planning injection ────────────────────────────────────────────────────────

def rules_text(rules_path: str) -> str:
    """Return a formatted prompt section for DeepSeek injection.

    Returns '' when no active rules exist.
    """
    active = list_rules(rules_path)
    if not active:
        return ""
    lines = ["## Project Rules (non-negotiable — enforce these in every task)\n"]
    for rule in active:
        lines.append(f"- {rule['text']}")
    return "\n".join(lines)


def format_rules(rules_path: str) -> str:
    """Return a human-readable rules listing for CLI display."""
    active = list_rules(rules_path)
    if not active:
        return "(no rules defined)"
    lines = []
    for i, rule in enumerate(active, 1):
        src = rule.get("source", "manual")
        ts = rule.get("created_at", "")[:10]
        lines.append(f"  {i}. [{rule['id']}]  {rule['text']}")
        lines.append(f"       source={src}  added={ts}")
    return "\n".join(lines)
