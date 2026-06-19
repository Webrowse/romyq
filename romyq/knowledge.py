"""Knowledge extraction and planning intelligence for Romyq.

Synthesizes lessons from execution memory, task history, event log, and
repository context into structured knowledge stored in .romyq/knowledge.json.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone


def _empty() -> dict:
    return {
        "version": 1,
        "generated_at": "",
        "structure_hash": "",
        "patterns": [],
        "lessons": [],
    }


def load(knowledge_path: str) -> dict:
    """Load knowledge.json, returning an empty structure on missing or corrupt."""
    try:
        with open(knowledge_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty()


def _write_atomic(knowledge_path: str, data: dict) -> None:
    dir_ = os.path.dirname(os.path.abspath(knowledge_path))
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, knowledge_path)


def _structure_hash(context_text: str, memory_entry_count: int, history_entry_count: int) -> str:
    """Compute a short hash capturing the structural state of all data sources."""
    payload = f"{memory_entry_count}:{history_entry_count}:{context_text[:500]}"
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _count_memory_entries(memory_path: str) -> int:
    try:
        with open(memory_path, encoding="utf-8") as f:
            data = json.load(f)
        return len(data.get("entries", []))
    except Exception:
        return 0


def _count_history_entries(history_path: str) -> int:
    try:
        with open(history_path, encoding="utf-8") as f:
            data = json.load(f)
        return len(data) if isinstance(data, list) else 0
    except Exception:
        return 0


def is_stale(
    knowledge_path: str,
    memory_path: str,
    history_path: str,
    context_text: str = "",
) -> bool:
    """Return True if knowledge.json is missing or outdated."""
    existing = load(knowledge_path)
    if not existing.get("generated_at"):
        return True
    mem_count = _count_memory_entries(memory_path)
    hist_count = _count_history_entries(history_path)
    current_hash = _structure_hash(context_text, mem_count, hist_count)
    return existing.get("structure_hash", "") != current_hash


def _extract_failure_patterns(memory_path: str, limit: int = 20) -> list[dict]:
    """Extract recurring failure patterns from memory.json."""
    try:
        from . import memory as mem_mod
        top = mem_mod.most_failed(memory_path, limit=limit)
        patterns = []
        for fp, count, preview, last_reason in top:
            if count < 2:
                continue
            patterns.append({
                "type": "failure_pattern",
                "fingerprint": fp,
                "task_preview": preview[:120],
                "count": count,
                "last_reason": last_reason[:200] if last_reason else "",
            })
        return patterns
    except Exception:
        return []


def _extract_success_patterns(memory_path: str, limit: int = 10) -> list[dict]:
    """Extract frequently successful tasks from memory.json."""
    try:
        with open(memory_path, encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("entries", [])
        success_entries = [e for e in entries if e.get("out") == "SUCCESS"]
        by_fp: dict[str, list] = {}
        for e in success_entries:
            fp = e.get("fp", "")
            if fp:
                by_fp.setdefault(fp, []).append(e)
        sorted_fps = sorted(by_fp.items(), key=lambda x: len(x[1]), reverse=True)[:limit]
        patterns = []
        for fp, execs in sorted_fps:
            preview = execs[0].get("task", "")[:120].replace("\n", " ")
            patterns.append({
                "type": "success_pattern",
                "fingerprint": fp,
                "task_preview": preview,
                "count": len(execs),
            })
        return patterns
    except Exception:
        return []


def _synthesize_lessons(
    failure_patterns: list[dict],
    history_path: str,
    events_path: str,
    context_text: str,
    memory_path: str,
) -> list[str]:
    """Synthesize human-readable lessons from all data sources."""
    lessons: list[str] = []

    # Lessons from recurring failure patterns
    for p in failure_patterns[:8]:
        preview = p["task_preview"][:80].replace("\n", " ")
        reason = p["last_reason"][:100].replace("\n", " ") if p.get("last_reason") else "unknown"
        count = p["count"]
        lessons.append(
            f"Task '{preview}' failed {count} times — last: {reason}. "
            "Avoid repeating this approach."
        )

    # Rate-limit pattern from events
    try:
        from .events import count_by_type
        counts = count_by_type(events_path)
        rl_count = counts.get("rate_limit_detected", 0)
        if rl_count >= 3:
            lessons.append(
                f"Rate limits triggered {rl_count} times. "
                "Break large tasks into smaller chunks."
            )
    except Exception:
        pass

    # Consecutive same-reason failures (recent history)
    try:
        from .history import recent as history_recent
        entries = history_recent(limit=50, path=history_path)
        failed = [e for e in entries if not e.get("success")]
        if len(failed) >= 5:
            recent_reasons = [e.get("validation_reason", "") for e in failed[-5:]]
            unique_reasons = set(r for r in recent_reasons if r)
            if len(unique_reasons) == 1:
                reason = unique_reasons.pop()[:100]
                lessons.append(
                    f"Recent failures share root cause: '{reason}'. "
                    "Address this before adding features."
                )
    except Exception:
        pass

    # Context-driven convention lessons
    if context_text:
        ctx_lower = context_text.lower()
        if "mypy" in ctx_lower or "pyright" in ctx_lower:
            lessons.append("Type checker is configured. New code must pass type checks.")
        if "ruff" in ctx_lower or "flake8" in ctx_lower or "pylint" in ctx_lower:
            lessons.append("Linter is configured. New code must pass linting before committing.")
        if "pytest" in ctx_lower or "unittest" in ctx_lower:
            lessons.append(
                "Test suite is present. Implementation tasks should include or update tests."
            )
        if "pre-commit" in ctx_lower or "husky" in ctx_lower:
            lessons.append(
                "Pre-commit hooks are configured. Commits failing hooks cause task failures."
            )

    return lessons


def generate(
    knowledge_path: str,
    memory_path: str,
    history_path: str,
    events_path: str,
    context_text: str = "",
) -> dict:
    """Generate a fresh knowledge structure from all data sources."""
    failure_patterns = _extract_failure_patterns(memory_path)
    success_patterns = _extract_success_patterns(memory_path)
    all_patterns = failure_patterns + success_patterns

    lessons = _synthesize_lessons(
        failure_patterns=failure_patterns,
        history_path=history_path,
        events_path=events_path,
        context_text=context_text,
        memory_path=memory_path,
    )

    mem_count = _count_memory_entries(memory_path)
    hist_count = _count_history_entries(history_path)
    struct_hash = _structure_hash(context_text, mem_count, hist_count)

    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "structure_hash": struct_hash,
        "patterns": all_patterns,
        "lessons": lessons,
    }


def write(
    knowledge_path: str,
    memory_path: str,
    history_path: str,
    events_path: str,
    context_text: str = "",
) -> str:
    """Generate and atomically write knowledge.json. Returns the path."""
    data = generate(knowledge_path, memory_path, history_path, events_path, context_text)
    _write_atomic(knowledge_path, data)
    return knowledge_path


def lessons_text(knowledge_path: str, limit: int = 10) -> str:
    """Return a formatted prompt section with synthesized lessons.

    Returns '' when no lessons are available.
    """
    data = load(knowledge_path)
    lessons = data.get("lessons", [])
    if not lessons:
        return ""
    shown = lessons[:limit]
    lines = [f"## Knowledge Base — Synthesized Lessons ({len(shown)} shown)\n"]
    lines.append("Apply these lessons when planning the next task:\n")
    for i, lesson in enumerate(shown, 1):
        lines.append(f"{i}. {lesson}")
    return "\n".join(lines)


def top_failure_patterns(knowledge_path: str, limit: int = 10) -> list[dict]:
    """Return top failure patterns from the knowledge base, sorted by count."""
    data = load(knowledge_path)
    patterns = data.get("patterns", [])
    failures = [p for p in patterns if p.get("type") == "failure_pattern"]
    return sorted(failures, key=lambda p: p.get("count", 0), reverse=True)[:limit]


def top_success_patterns(knowledge_path: str, limit: int = 10) -> list[dict]:
    """Return top success patterns from the knowledge base, sorted by count."""
    data = load(knowledge_path)
    patterns = data.get("patterns", [])
    successes = [p for p in patterns if p.get("type") == "success_pattern"]
    return sorted(successes, key=lambda p: p.get("count", 0), reverse=True)[:limit]
