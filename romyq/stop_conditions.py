"""Stop Conditions — "Good Enough" evaluation for Romyq.

Evaluates whether the project has reached a stopping point so operators
know when to actually stop instead of running forever.

Outputs a recommendation: "Continue" or "Stop".
"""
from __future__ import annotations

DEFAULT_THRESHOLD = 80  # overall readiness % to recommend Stop


def _check_core_complete(readiness: dict, state: dict, threshold: float) -> bool:
    """True when Core Functionality category is 100%."""
    cats = readiness.get("categories", {})
    core = cats.get("Core Functionality", {})
    return core.get("score", 0) >= 100.0


# Named conditions: (condition_name, check_fn(readiness, state, threshold) -> bool)
_CONDITIONS: list[tuple[str, object]] = [
    ("readiness_above_threshold", lambda r, s, t: r.get("overall", 0) >= t),
    ("mission_complete", lambda r, s, t: s.get("status") == "completed"),
    ("core_capabilities_complete", _check_core_complete),
]


def evaluate(
    readiness: dict,
    state: dict,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """Evaluate stop conditions and return a recommendation.

    Result keys:
      recommendation   "Stop" | "Continue"
      reasons          list[str] — why we recommend Stop or Continue
      overall_readiness  float
      threshold        float
      conditions       {name: bool}
      should_stop      bool
    """
    condition_results: dict[str, bool] = {}
    for name, check_fn in _CONDITIONS:
        try:
            result = check_fn(readiness, state, threshold)  # type: ignore[operator]
        except Exception:
            result = False
        condition_results[name] = bool(result)

    should_stop = any(condition_results.values())

    reasons: list[str] = []
    if should_stop:
        reasons = [n for n, met in condition_results.items() if met]
        recommendation = "Stop"
    else:
        reasons = [n for n, met in condition_results.items() if not met][:3]
        recommendation = "Continue"

    return {
        "recommendation": recommendation,
        "should_stop": should_stop,
        "reasons": reasons,
        "overall_readiness": readiness.get("overall", 0),
        "threshold": threshold,
        "conditions": condition_results,
    }


def format_stop_conditions(result: dict) -> str:
    """Return a human-readable stop condition summary."""
    rec = result.get("recommendation", "Continue")
    overall = result.get("overall_readiness", 0)
    threshold = result.get("threshold", DEFAULT_THRESHOLD)
    lines = [
        f"Recommendation: {rec}",
        f"Overall Readiness: {overall:.0f}% (threshold: {threshold:.0f}%)",
        "",
    ]
    conds = result.get("conditions", {})
    for name, met in conds.items():
        icon = "✓" if met else "✗"
        label = name.replace("_", " ").capitalize()
        lines.append(f"  {icon} {label}")
    reasons = result.get("reasons", [])
    if reasons:
        lines.append("")
        prefix = "Why stop:" if rec == "Stop" else "Still needed:"
        lines.append(prefix)
        for r in reasons:
            lines.append(f"  - {r.replace('_', ' ')}")
    return "\n".join(lines)
