"""Software lifecycle model — phases, tasks, progress tracking, done criteria.

.romyq/lifecycle.json structure:
{
  "version": 1,
  "project": "Scientific Calculator",
  "complexity": "intermediate",
  "generated_at": "2026-01-01T00:00:00+00:00",
  "current_phase_id": 2,
  "done_criteria": ["software runs", "tests pass", "README exists"],
  "phases": [
    {
      "id": 1,
      "name": "Project Setup",
      "status": "complete",
      "total_tasks": 2,
      "completed_tasks": 2,
      "current_task": null,
      "percentage_complete": 100,
      "tasks": [
        {"id": "1.1", "text": "...", "status": "complete", "completed_at": "..."}
      ]
    },
    {
      "id": 2,
      "name": "Core Engine",
      "status": "active",
      "total_tasks": 3,
      "completed_tasks": 1,
      "current_task": "2.2",
      "percentage_complete": 33,
      "tasks": [
        {"id": "2.1", "text": "...", "status": "complete", "completed_at": "..."},
        {"id": "2.2", "text": "...", "status": "active", "completed_at": null},
        {"id": "2.3", "text": "...", "status": "pending", "completed_at": null}
      ]
    }
  ]
}
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone

_VERSION = 1
PHASE_STATUSES = frozenset({"pending", "active", "complete"})
TASK_STATUSES = frozenset({"pending", "active", "complete", "skipped"})

_SYSTEM_PROMPT = (
    "You are a senior software architect. "
    "Generate a structured software project lifecycle."
)

_LIFECYCLE_PROMPT = """\
Create a software project lifecycle for the mission below.

Mission:
{mission}

Complexity level: {complexity}

Complexity guidance:
{complexity_guidance}

Return ONLY valid JSON with this exact structure:
{{
  "phases": [
    {{
      "id": 1,
      "name": "Phase Name",
      "tasks": [
        {{"id": "1.1", "text": "Concrete task description"}},
        {{"id": "1.2", "text": "Another task"}}
      ]
    }}
  ]
}}

Rules:
- Each phase must have 2-5 tasks.
- Tasks must be concrete and independently completable ending with a git commit.
- Phase names describe the deliverable (e.g. "Project Setup", "Core Engine", "User Interface", "Testing", "Packaging").
- Follow the complexity level — basic has fewer phases and simpler tasks.
- No planning or discussion tasks. Only implementation tasks.
- Output ONLY the JSON object. No markdown, no explanation.
"""

_COMPLEXITY_GUIDANCE = {
    "basic": "2-3 phases. Focus on making the software work. No CI, no docs required.",
    "intermediate": "3-5 phases. Include testing phase and README. Basic CI is good.",
    "advanced": "5-7 phases. Include security, monitoring, deployment, comprehensive docs and CI/CD.",
}


# ── persistence ───────────────────────────────────────────────────────────────

def _empty() -> dict:
    return {
        "version": _VERSION,
        "project": "",
        "complexity": "intermediate",
        "generated_at": "",
        "current_phase_id": None,
        "done_criteria": [],
        "phases": [],
    }


def load(lifecycle_path: str) -> dict:
    """Load lifecycle.json, returning an empty structure on missing or corrupt."""
    try:
        with open(lifecycle_path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty()
        data.setdefault("version", _VERSION)
        data.setdefault("project", "")
        data.setdefault("complexity", "intermediate")
        data.setdefault("generated_at", "")
        data.setdefault("current_phase_id", None)
        data.setdefault("done_criteria", [])
        data.setdefault("phases", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return _empty()


def _write_atomic(lifecycle_path: str, data: dict) -> None:
    dir_ = os.path.dirname(os.path.abspath(lifecycle_path))
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, lifecycle_path)


def save(lifecycle_path: str, data: dict) -> None:
    """Atomically write lifecycle.json."""
    _write_atomic(lifecycle_path, data)


# ── parsing ───────────────────────────────────────────────────────────────────

def _parse_lifecycle_from_text(text: str) -> list[dict] | None:
    """Extract phase list from LLM output (JSON or partial JSON)."""
    text = text.strip()
    # Strip markdown code fences
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"```\s*$", "", text, flags=re.MULTILINE)
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict) and "phases" in data:
            return data["phases"]
    except json.JSONDecodeError:
        pass

    # Try to extract the outermost JSON object
    brace_start = text.find("{")
    if brace_start >= 0:
        depth = 0
        for i, ch in enumerate(text[brace_start:], start=brace_start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        candidate = json.loads(text[brace_start : i + 1])
                        if isinstance(candidate, dict) and "phases" in candidate:
                            return candidate["phases"]
                    except json.JSONDecodeError:
                        break

    return None


def _validate_phases(raw_phases: list) -> list[dict]:
    """Validate and normalise the phase list from LLM output."""
    phases = []
    for i, raw in enumerate(raw_phases, start=1):
        if not isinstance(raw, dict):
            continue
        phase_id = raw.get("id", i)
        name = str(raw.get("name", f"Phase {phase_id}"))
        raw_tasks = raw.get("tasks", [])
        if not isinstance(raw_tasks, list):
            raw_tasks = []

        tasks = []
        for j, t in enumerate(raw_tasks, start=1):
            if not isinstance(t, dict):
                continue
            task_id = str(t.get("id", f"{phase_id}.{j}"))
            task_text = str(t.get("text", "")).strip()
            if len(task_text) < 5:
                continue
            tasks.append({
                "id": task_id,
                "text": task_text,
                "status": "pending",
                "completed_at": None,
            })

        if not tasks:
            continue

        phases.append({
            "id": phase_id,
            "name": name,
            "status": "pending",
            "total_tasks": len(tasks),
            "completed_tasks": 0,
            "current_task": None,
            "percentage_complete": 0,
            "tasks": tasks,
        })
    return phases


def _build_lifecycle(
    phases: list[dict],
    mission: str,
    complexity: str,
    done_criteria: list[str],
    source: str = "deepseek",
) -> dict:
    """Assemble a full lifecycle dict from validated phases."""
    enriched = list(phases)
    # Mark first phase as active
    if enriched:
        enriched[0]["status"] = "active"
        first_task_id = enriched[0]["tasks"][0]["id"] if enriched[0]["tasks"] else None
        enriched[0]["current_task"] = first_task_id
        if first_task_id:
            enriched[0]["tasks"][0]["status"] = "active"

    current_phase_id = enriched[0]["id"] if enriched else None

    return {
        "version": _VERSION,
        "project": mission[:200],
        "complexity": complexity,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "current_phase_id": current_phase_id,
        "done_criteria": done_criteria,
        "phases": enriched,
        "source": source,
    }


# ── generation (requires DeepSeek) ───────────────────────────────────────────

class LifecycleGenerationError(Exception):
    """Raised when DeepSeek lifecycle generation fails and no fallback should be used."""


def generate(
    api_key: str,
    mission: str,
    complexity: str = "intermediate",
    done_criteria: list[str] | None = None,
) -> dict:
    """Call DeepSeek to generate a lifecycle for the mission.

    Returns a lifecycle dict with a 'source' field: 'deepseek' or 'local_fallback'.
    Never raises — falls back to _default_phases() on API failure.
    Callers should check data['source'] to determine whether DeepSeek was used.
    """
    from romyq.profile import COMPLEXITY_CONFIG
    if done_criteria is None:
        done_criteria = list(
            COMPLEXITY_CONFIG.get(complexity, COMPLEXITY_CONFIG["intermediate"])["done_criteria"]
        )

    guidance = _COMPLEXITY_GUIDANCE.get(complexity, _COMPLEXITY_GUIDANCE["intermediate"])
    prompt = _LIFECYCLE_PROMPT.format(
        mission=mission[:2000],
        complexity=complexity,
        complexity_guidance=guidance,
    )

    _source = "deepseek"
    try:
        from .provider import chat as provider_chat
        raw = provider_chat(
            api_key,
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            max_tokens=2048,
        )
        raw_phases = _parse_lifecycle_from_text(raw)
        if not raw_phases:
            raise ValueError("no phases parsed from LLM output")
        phases = _validate_phases(raw_phases)
    except Exception:
        phases = _default_phases(complexity)
        _source = "local_fallback"

    return _build_lifecycle(phases, mission, complexity, done_criteria, source=_source)


def _default_phases(complexity: str) -> list[dict]:
    """Minimal fallback phases when LLM call fails."""
    base = [
        {"id": 1, "name": "Project Setup", "tasks": [
            {"id": "1.1", "text": "Initialize project structure and configuration"},
            {"id": "1.2", "text": "Set up dependencies and development environment"},
        ]},
        {"id": 2, "name": "Core Implementation", "tasks": [
            {"id": "2.1", "text": "Implement core business logic"},
            {"id": "2.2", "text": "Add input validation and error handling"},
            {"id": "2.3", "text": "Write unit tests for core functionality"},
        ]},
    ]
    if complexity in ("intermediate", "advanced"):
        base.append({"id": 3, "name": "Testing & Documentation", "tasks": [
            {"id": "3.1", "text": "Write integration tests"},
            {"id": "3.2", "text": "Create README with usage examples"},
        ]})
    if complexity == "advanced":
        base.extend([
            {"id": 4, "name": "Security & Observability", "tasks": [
                {"id": "4.1", "text": "Implement authentication and authorization"},
                {"id": "4.2", "text": "Add logging and monitoring"},
            ]},
            {"id": 5, "name": "Deployment", "tasks": [
                {"id": "5.1", "text": "Set up CI/CD pipeline"},
                {"id": "5.2", "text": "Create deployment configuration"},
            ]},
        ])
    return _validate_phases(base)


# ── phase and task navigation ─────────────────────────────────────────────────

def current_phase(data: dict) -> dict | None:
    """Return the currently active phase dict, or None."""
    current_id = data.get("current_phase_id")
    for phase in data.get("phases", []):
        if phase.get("id") == current_id:
            return phase
    return None


def next_pending_task(data: dict) -> tuple[dict | None, dict | None]:
    """Return (phase, task) for the next pending task, or (None, None)."""
    phase = current_phase(data)
    if phase is None:
        return None, None
    for task in phase.get("tasks", []):
        if task.get("status") in ("pending", "active"):
            return phase, task
    return None, None


def all_phases_complete(data: dict) -> bool:
    """Return True when every phase has status 'complete'."""
    phases = data.get("phases", [])
    if not phases:
        return False
    return all(p.get("status") == "complete" for p in phases)


# ── mutations ─────────────────────────────────────────────────────────────────

def _recompute_phase_progress(phase: dict) -> None:
    """Recompute total_tasks, completed_tasks, percentage_complete in-place."""
    tasks = phase.get("tasks", [])
    total = len(tasks)
    done = sum(1 for t in tasks if t.get("status") == "complete")
    phase["total_tasks"] = total
    phase["completed_tasks"] = done
    phase["percentage_complete"] = int(done * 100 / total) if total else 0


def mark_task_complete(lifecycle_path: str, phase_id: int | str, task_id: str) -> bool:
    """Mark a task complete, advance the phase, return True if found."""
    data = load(lifecycle_path)
    phase_id = int(phase_id) if isinstance(phase_id, str) and phase_id.isdigit() else phase_id

    for phase in data.get("phases", []):
        if phase.get("id") != phase_id:
            continue
        for task in phase.get("tasks", []):
            if task.get("id") != task_id:
                continue
            task["status"] = "complete"
            task["completed_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            _recompute_phase_progress(phase)

            # Find next pending task in this phase
            next_task = next(
                (t for t in phase["tasks"] if t.get("status") == "pending"),
                None,
            )
            if next_task:
                next_task["status"] = "active"
                phase["current_task"] = next_task["id"]
            else:
                phase["current_task"] = None
                phase["status"] = "complete"
                _advance_phase(data)

            _write_atomic(lifecycle_path, data)
            return True
    return False


def _advance_phase(data: dict) -> None:
    """Move current_phase_id to the next pending phase."""
    phases = data.get("phases", [])
    for phase in phases:
        if phase.get("status") == "pending":
            phase["status"] = "active"
            data["current_phase_id"] = phase["id"]
            # Mark first task active
            if phase.get("tasks"):
                phase["tasks"][0]["status"] = "active"
                phase["current_task"] = phase["tasks"][0]["id"]
            return
    # No more phases — all done
    data["current_phase_id"] = None


def mark_task_active(lifecycle_path: str, phase_id: int | str, task_id: str) -> bool:
    """Mark a task as active (currently being worked on)."""
    data = load(lifecycle_path)
    phase_id = int(phase_id) if isinstance(phase_id, str) and phase_id.isdigit() else phase_id

    for phase in data.get("phases", []):
        if phase.get("id") != phase_id:
            continue
        for task in phase.get("tasks", []):
            if task.get("id") != task_id:
                continue
            task["status"] = "active"
            phase["current_task"] = task_id
            _write_atomic(lifecycle_path, data)
            return True
    return False


def skip_task(lifecycle_path: str, phase_id: int | str, task_id: str) -> bool:
    """Skip a task and advance to the next."""
    data = load(lifecycle_path)
    phase_id = int(phase_id) if isinstance(phase_id, str) and phase_id.isdigit() else phase_id

    for phase in data.get("phases", []):
        if phase.get("id") != phase_id:
            continue
        for task in phase.get("tasks", []):
            if task.get("id") != task_id:
                continue
            task["status"] = "skipped"
            _recompute_phase_progress(phase)
            next_task = next(
                (t for t in phase["tasks"] if t.get("status") == "pending"),
                None,
            )
            if next_task:
                next_task["status"] = "active"
                phase["current_task"] = next_task["id"]
            else:
                remaining = [t for t in phase["tasks"] if t.get("status") not in ("complete", "skipped")]
                if not remaining:
                    phase["status"] = "complete"
                    phase["current_task"] = None
                    _advance_phase(data)
            _write_atomic(lifecycle_path, data)
            return True
    return False


def reset_active_tasks(lifecycle_path: str) -> None:
    """Reset any active tasks to pending (called on loop restart)."""
    data = load(lifecycle_path)
    changed = False
    for phase in data.get("phases", []):
        for task in phase.get("tasks", []):
            if task.get("status") == "active":
                task["status"] = "pending"
                changed = True
    if changed:
        _write_atomic(lifecycle_path, data)


# ── summary & display ─────────────────────────────────────────────────────────

def progress_summary(data: dict) -> dict:
    """Return overall progress counts."""
    phases = data.get("phases", [])
    total_tasks = sum(p.get("total_tasks", len(p.get("tasks", []))) for p in phases)
    completed_tasks = sum(p.get("completed_tasks", 0) for p in phases)
    complete_phases = sum(1 for p in phases if p.get("status") == "complete")
    return {
        "total_phases": len(phases),
        "complete_phases": complete_phases,
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "remaining_tasks": total_tasks - completed_tasks,
        "overall_percentage": int(completed_tasks * 100 / total_tasks) if total_tasks else 0,
    }


def format_roadmap(data: dict) -> str:
    """Return a human-readable roadmap."""
    phases = data.get("phases", [])
    if not phases:
        return "(no lifecycle generated)"

    lines: list[str] = []
    current_id = data.get("current_phase_id")

    for phase in phases:
        status = phase.get("status", "pending")
        pct = phase.get("percentage_complete", 0)
        name = phase.get("name", f"Phase {phase.get('id', '?')}")

        if status == "complete":
            icon = "✓"
            bar = f"100%"
        elif status == "active":
            icon = "→"
            bar = f"{pct}%"
        else:
            icon = "□"
            bar = "0%"

        lines.append(f"  {icon} {name:30s}  {bar}")

    summary = progress_summary(data)
    lines.insert(0, f"Phases: {summary['complete_phases']}/{summary['total_phases']}  "
                    f"Tasks: {summary['completed_tasks']}/{summary['total_tasks']}")
    return "\n".join(lines)


def format_current_phase(data: dict) -> str:
    """Return a human-readable view of the current phase and its tasks."""
    phase = current_phase(data)
    if phase is None:
        if all_phases_complete(data):
            return "All phases complete."
        return "(no active phase)"

    icons = {"pending": "□", "active": "→", "complete": "✓", "skipped": "–"}
    lines = [f"Phase {phase['id']}: {phase['name']} ({phase.get('percentage_complete', 0)}%)"]
    for task in phase.get("tasks", []):
        icon = icons.get(task.get("status", "pending"), "□")
        lines.append(f"  {icon} [{task['id']}] {task['text']}")
    return "\n".join(lines)
