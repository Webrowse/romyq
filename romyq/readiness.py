"""Mission Readiness Score — outcome-centric progress across categories.

Answers "Can I stop now?" by scoring categories that operators care about:
  Core Functionality, Testing, Security, Operations

Score is 0-100; a threshold of 80 is the "Good Enough" default.
"""
from __future__ import annotations

from .capabilities import STATUS_SCORES

# Readiness category weights (must sum to 1.0)
_CATEGORY_WEIGHTS: dict[str, float] = {
    "Core Functionality": 0.40,
    "Testing": 0.25,
    "Security": 0.20,
    "Operations": 0.15,
}

# Which capabilities contribute to each readiness category
_CATEGORY_CAPABILITY_MAP: dict[str, list[str]] = {
    "Core Functionality": ["Core Features", "Database", "Validation"],
    "Testing": ["Testing"],
    "Security": ["Security", "Authentication", "Authorization"],
    "Operations": ["Deployment", "Observability", "Documentation"],
}

READINESS_CATEGORIES = list(_CATEGORY_WEIGHTS.keys())


def _category_score(capabilities: list[dict], required_caps: list[str]) -> float:
    """0–100 for one category.  Missing capabilities count as 0."""
    if not required_caps:
        return 0.0
    total = 0.0
    for cap_name in required_caps:
        matched = next(
            (c for c in capabilities if c.get("name", "").lower() == cap_name.lower()),
            None,
        )
        status = matched["status"] if matched else "missing"
        total += STATUS_SCORES.get(status, 0)
    return total / len(required_caps)


def compute(capabilities: list[dict]) -> dict:
    """Return readiness dict.

    Result keys:
      overall         0-100 weighted score
      categories      {name: {score, required, statuses}}
      label           "Not Ready" | "Approaching" | "Ready" | "Excellent"
    """
    category_results: dict[str, dict] = {}
    weighted_sum = 0.0

    for cat, weight in _CATEGORY_WEIGHTS.items():
        required = _CATEGORY_CAPABILITY_MAP.get(cat, [])
        score = _category_score(capabilities, required)
        statuses = {}
        for cap_name in required:
            matched = next(
                (c for c in capabilities if c.get("name", "").lower() == cap_name.lower()),
                None,
            )
            statuses[cap_name] = matched["status"] if matched else "missing"
        category_results[cat] = {
            "score": round(score, 1),
            "required": required,
            "statuses": statuses,
        }
        weighted_sum += score * weight

    overall = round(weighted_sum, 1)
    label = _label(overall)

    return {
        "overall": overall,
        "label": label,
        "categories": category_results,
    }


def compute_from_path(project_state_path: str) -> dict:
    """Load capabilities from disk then compute readiness."""
    from .capabilities import list_capabilities
    caps = list_capabilities(project_state_path)
    return compute(caps)


def _label(score: float) -> str:
    if score >= 90:
        return "Excellent"
    if score >= 80:
        return "Ready"
    if score >= 50:
        return "Approaching"
    return "Not Ready"


def format_readiness(readiness: dict) -> str:
    """Return a human-readable readiness report."""
    overall = readiness.get("overall", 0)
    label = readiness.get("label", "")
    lines = [f"Mission Readiness: {overall:.0f}%  [{label}]", ""]
    cats = readiness.get("categories", {})
    for cat, info in cats.items():
        pct = info.get("score", 0)
        bar = _bar(pct)
        lines.append(f"  {cat:<22}  {bar}  {pct:>5.1f}%")
        for cap, status in info.get("statuses", {}).items():
            from .capabilities import STATUS_ICONS
            icon = STATUS_ICONS.get(status, "?")
            lines.append(f"    {icon} {cap}")
    return "\n".join(lines)


def _bar(pct: float, width: int = 10) -> str:
    filled = round(pct / 100 * width)
    return "[" + "█" * filled + "░" * (width - filled) + "]"
