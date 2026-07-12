"""Wizard business logic — all testable without Textual.

Handles .env writing, mission.md writing, git setup, and the complete
wizard_setup() sequence used by both the Textual wizard and the text fallback.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

_DEMO_MISSION = """\
Build a minimal REST API for a to-do application.

Requirements:
- POST /tasks — create a task with title and optional description
- GET /tasks — list all tasks
- GET /tasks/{id} — fetch a single task
- PATCH /tasks/{id} — update a task (title or done status)
- DELETE /tasks/{id} — remove a task

Technical stack:
- Python 3.10+
- FastAPI
- SQLite (via SQLAlchemy or sqlite3)
- pytest for tests

Each endpoint must have at least one test.
Commit working code after each endpoint is implemented.
"""

from .provider import KNOWN_PROVIDERS

PROVIDERS: dict[str, dict] = {
    pid: {"name": cfg["label"], **cfg} for pid, cfg in KNOWN_PROVIDERS.items()
}


def demo_mission() -> str:
    """Return the built-in demo mission text."""
    return _DEMO_MISSION


def validate_api_key(key: str, provider: str = "deepseek") -> bool:
    """Basic structural validation — no network calls."""
    key = key.strip()
    return len(key) >= 10


def write_env(
    workspace: str,
    api_key: str,
    provider: str = "deepseek",
    base_url: str = "",
    model: str = "",
) -> str:
    """Write or update the planner configuration in workspace/.env.

    DeepSeek writes only DEEPSEEK_API_KEY (backward compatible). Any other
    provider writes the ROMYQ_PLANNER_* trio so the runtime targets the
    right endpoint. Creates the file if absent; updates lines in place.
    Returns the path to .env.
    """
    env_path = Path(workspace) / ".env"

    if provider == "deepseek":
        entries = [("DEEPSEEK_API_KEY", api_key.strip())]
    else:
        cfg = PROVIDERS.get(provider, {})
        entries = [
            ("ROMYQ_PLANNER_API_KEY", api_key.strip()),
            ("ROMYQ_PLANNER_BASE_URL", base_url or cfg.get("base_url", "")),
            ("ROMYQ_PLANNER_MODEL", model or cfg.get("model", "")),
        ]

    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()

    for var, value in entries:
        new_line = f"{var}={value}"
        for i, line in enumerate(lines):
            if line.startswith(f"{var}="):
                lines[i] = new_line
                break
        else:
            lines.append(new_line)

    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(env_path)


def read_env_key(workspace: str, provider: str = "deepseek") -> str:
    """Read the API key from workspace/.env, returning '' if absent."""
    env_path = Path(workspace) / ".env"
    provider_cfg = PROVIDERS.get(provider, PROVIDERS["deepseek"])
    key_var = provider_cfg["key_var"]
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{key_var}="):
            return line.split("=", 1)[1].strip()
    return ""


def write_mission(workspace: str, mission_text: str) -> str:
    """Write mission.md to workspace. Returns the path."""
    mission_path = Path(workspace) / "mission.md"
    mission_path.write_text(mission_text.strip() + "\n", encoding="utf-8")
    return str(mission_path)


def setup_git(workspace: str) -> tuple[bool, str]:
    """Initialize a git repository if one does not already exist.

    Returns (success: bool, message: str).
    """
    from .workspace import is_git_repo, _ensure_gitignore_entry

    root = Path(workspace).resolve()
    if is_git_repo(str(root)):
        return True, "Already a git repository."

    try:
        result = subprocess.run(
            ["git", "init"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return False, f"git init failed: {result.stderr[:200]}"
        _ensure_gitignore_entry(str(root), ".romyq/")
        _ensure_gitignore_entry(str(root), ".env")
        return True, "Git repository initialized."
    except FileNotFoundError:
        return False, "git not found in PATH."
    except Exception as e:
        return False, f"git init error: {e}"


def add_gitignore_entries(workspace: str) -> None:
    """Ensure .romyq/ and .env are in .gitignore."""
    from .workspace import _ensure_gitignore_entry
    _ensure_gitignore_entry(workspace, ".romyq/")
    _ensure_gitignore_entry(workspace, ".env")


def setup_workspace(workspace: str) -> str:
    """Create the .romyq/ state directory. Returns the romyq dir path."""
    from . import store
    return str(store.ensure_dir(workspace))


def wizard_setup(
    workspace: str,
    api_key: str,
    mission_text: str,
    provider: str = "deepseek",
    init_git: bool = True,
    base_url: str = "",
    model: str = "",
) -> dict[str, str]:
    """Execute the complete wizard setup sequence.

    Returns a dict mapping step name → result string.
    All errors are captured; individual step failures do not abort the sequence.
    """
    results: dict[str, str] = {}

    # 1. API key
    try:
        write_env(workspace, api_key, provider, base_url=base_url, model=model)
        results["api_key"] = "configured"
    except Exception as e:
        results["api_key"] = f"failed: {e}"

    # 2. Mission
    try:
        write_mission(workspace, mission_text)
        results["mission"] = "saved"
    except Exception as e:
        results["mission"] = f"failed: {e}"

    # 3. Git
    if init_git:
        ok, msg = setup_git(workspace)
        results["git"] = "initialized" if ok else f"skipped ({msg})"
    else:
        results["git"] = "skipped (--no-vcs)"

    # 4. State directory
    try:
        setup_workspace(workspace)
        results["state_dir"] = "created"
    except Exception as e:
        results["state_dir"] = f"failed: {e}"

    return results
