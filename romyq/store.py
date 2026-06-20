"""
Central authority for .romyq/ directory layout and legacy migration.

All runtime state for a managed workspace lives in {workspace}/.romyq/:
  state.json    — current run state (tasks completed, heartbeat, …)
  history.json  — per-task result log
  findings.json — audit findings
  state.md      — human-readable summary of the last task
  notes.md      — human steering notes (appended via `romyq note`)
"""
import shutil
from pathlib import Path

ROMYQ_DIR = ".romyq"

_STATE_FILE = "state.json"
_HISTORY_FILE = "history.json"
_FINDINGS_FILE = "findings.json"
_STATE_MD = "state.md"
_NOTES_FILE = "notes.md"
_EVENTS_FILE = "events.log"
_CONTEXT_FILE    = "context.md"
_MEMORY_FILE     = "memory.json"
_KNOWLEDGE_FILE  = "knowledge.json"
_PLAN_FILE       = "plan.json"
_RULES_FILE          = "rules.json"
_DECISIONS_FILE      = "decisions.json"
_PROJECT_STATE_FILE  = "project_state.json"
_CONSTITUTION_FILE   = "project.md"
_LIFECYCLE_FILE      = "lifecycle.json"
_PROFILE_FILE        = "project_profile.json"

# Legacy CWD-relative names → new names inside .romyq/
_LEGACY = {
    "state.json": _STATE_FILE,
    "task_history.json": _HISTORY_FILE,
    "audit_report.json": _FINDINGS_FILE,
    "state.md": _STATE_MD,
}


def romyq_dir(workspace: str) -> Path:
    return Path(workspace).resolve() / ROMYQ_DIR


def ensure_dir(workspace: str) -> Path:
    d = romyq_dir(workspace)
    d.mkdir(parents=True, exist_ok=True)
    return d


def state_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _STATE_FILE)


def history_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _HISTORY_FILE)


def findings_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _FINDINGS_FILE)


def state_md_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _STATE_MD)


def notes_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _NOTES_FILE)


def events_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _EVENTS_FILE)


def context_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _CONTEXT_FILE)


def memory_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _MEMORY_FILE)


def knowledge_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _KNOWLEDGE_FILE)


def plan_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _PLAN_FILE)


def rules_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _RULES_FILE)


def decisions_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _DECISIONS_FILE)


def project_state_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _PROJECT_STATE_FILE)


def constitution_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _CONSTITUTION_FILE)


def lifecycle_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _LIFECYCLE_FILE)


def profile_path(workspace: str) -> str:
    return str(ensure_dir(workspace) / _PROFILE_FILE)


def migrate(workspace: str) -> list[str]:
    """Move any legacy CWD-based state files into {workspace}/.romyq/.

    Safe to call repeatedly — only moves files that exist in CWD and are
    absent from the target location.  Returns list of moved file descriptions.
    """
    d = ensure_dir(workspace)
    cwd = Path(".")
    moved: list[str] = []
    for legacy_name, new_name in _LEGACY.items():
        src = cwd / legacy_name
        dst = d / new_name
        if src.exists() and not dst.exists():
            shutil.move(str(src), str(dst))
            moved.append(f"{legacy_name} → .romyq/{new_name}")
    return moved
