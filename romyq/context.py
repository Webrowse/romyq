"""Repository memory — generate and persist .romyq/context.md.

Analyses the workspace using deterministic, AI-free static analysis and
produces a structured Markdown file that the planner includes in every
task-generation prompt.  Safe to regenerate at any time: re-running
`romyq learn` overwrites context.md with fresh analysis.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .workspace import detect as _detect


# ── CI / workflow detection ───────────────────────────────────────────────────

def _ci_workflows(root: Path) -> list[str]:
    found: list[str] = []
    gh = root / ".github" / "workflows"
    if gh.is_dir():
        ymls = sorted(p.name for p in gh.iterdir() if p.suffix in (".yml", ".yaml"))
        if ymls:
            found.append(f"GitHub Actions: {', '.join(ymls)}")
    for path, label in (
        (".gitlab-ci.yml", "GitLab CI"),
        ("Jenkinsfile", "Jenkins"),
        (".circleci/config.yml", "CircleCI"),
        (".travis.yml", "Travis CI"),
        ("bitbucket-pipelines.yml", "Bitbucket Pipelines"),
        ("azure-pipelines.yml", "Azure Pipelines"),
    ):
        if (root / path).exists():
            found.append(label)
    return found


# ── convention detection ──────────────────────────────────────────────────────

def _conventions(root: Path, d: dict) -> list[str]:
    found: list[str] = []

    # .editorconfig rules
    ec = root / ".editorconfig"
    if ec.exists():
        text = ec.read_text(encoding="utf-8", errors="ignore")
        if "indent_style = tab" in text:
            found.append("Indentation: tabs (editorconfig)")
        elif "indent_style = space" in text:
            for line in text.splitlines():
                if "indent_size" in line and "=" in line:
                    size = line.split("=", 1)[1].strip()
                    found.append(f"Indentation: {size} spaces (editorconfig)")
                    break

    # Python-specific
    if d.get("language") == "python":
        ppt = root / "pyproject.toml"
        if ppt.exists():
            text = ppt.read_text(encoding="utf-8", errors="ignore")
            if "ruff" in text:
                found.append("Linter: ruff")
            if "black" in text:
                found.append("Formatter: black")
            if "mypy" in text:
                found.append("Type checker: mypy")
            if "pytest" in text:
                found.append("Test runner: pytest")
        for req in ("requirements.txt", "requirements-dev.txt"):
            rf = root / req
            if rf.exists():
                text = rf.read_text(encoding="utf-8", errors="ignore").lower()
                if "black" in text:
                    found.append("Formatter: black (requirements)")

    # Rust-specific
    if d.get("language") == "rust":
        found.append("Test runner: cargo test")
        if (root / "rustfmt.toml").exists() or (root / ".rustfmt.toml").exists():
            found.append("Formatter: rustfmt")
        if (root / "clippy.toml").exists():
            found.append("Linter: clippy")

    # Node-specific
    if d.get("language") == "node":
        if (root / ".eslintrc.js").exists() or (root / ".eslintrc.json").exists() or (root / "eslint.config.js").exists():
            found.append("Linter: ESLint")
        if (root / ".prettierrc").exists() or (root / "prettier.config.js").exists():
            found.append("Formatter: Prettier")
        if (root / "tsconfig.json").exists():
            found.append("TypeScript: yes")

    # Go-specific
    if d.get("language") == "go":
        found.append("Test runner: go test ./...")
        found.append("Build: go build ./...")

    # Git hooks
    if (root / ".husky").is_dir():
        found.append("Git hooks: husky")
    if (root / ".pre-commit-config.yaml").exists():
        found.append("Git hooks: pre-commit")

    return found


# ── git metadata ──────────────────────────────────────────────────────────────

def _first_commit_date(root: Path) -> str:
    r = subprocess.run(
        ["git", "log", "--reverse", "--format=%ci", "--max-count=1"],
        cwd=root, capture_output=True, text=True,
    )
    return r.stdout.strip()[:10] if r.returncode == 0 else ""


# ── public API ────────────────────────────────────────────────────────────────

def generate(workspace: str, detect_result: dict | None = None) -> str:
    """Build the context.md content from static analysis.  No AI required."""
    root = Path(workspace).resolve()
    d = detect_result if detect_result is not None else _detect(workspace)

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    lines: list[str] = [
        "# Repository Context",
        "",
        f"Generated: {now}",
        f"Workspace: {root}",
        "",
        "## Project Type",
        d.get("language", "unknown"),
        "",
    ]

    if d.get("frameworks"):
        lines += ["## Frameworks / Libraries"] + [f"- {f}" for f in d["frameworks"]] + [""]

    build_cmds = d.get("build_commands", [])
    if build_cmds:
        lines += ["## Build Commands"] + [f"- {c}" for c in build_cmds[:8]] + [""]

    test_fw = d.get("test_framework")
    test_detail = d.get("test_detail", "")
    if test_fw or test_detail:
        lines += ["## Test Commands"]
        if test_fw:
            lines.append(f"- {test_fw}")
        if test_detail:
            lines.append(f"  ({test_detail})")
        lines.append("")

    if d.get("entry_points"):
        lines += ["## Entry Points"] + [f"- {e}" for e in d["entry_points"]] + [""]

    if d.get("structure"):
        lines += ["## Directory Structure"] + [f"- {s}" for s in d["structure"]] + [""]

    ci = _ci_workflows(root)
    if ci:
        lines += ["## CI / CD"] + [f"- {c}" for c in ci] + [""]

    conv = _conventions(root, d)
    if conv:
        lines += ["## Conventions"] + [f"- {c}" for c in conv] + [""]

    first_date = _first_commit_date(root)
    if first_date:
        lines += [f"## Repository Age", f"First commit: {first_date}", ""]

    return "\n".join(lines)


def write(workspace: str, detect_result: dict | None = None) -> str:
    """Generate context.md and write it atomically.  Returns the path written."""
    from . import store
    content = generate(workspace, detect_result=detect_result)
    path = store.context_path(workspace)
    dir_ = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, path)
    return path


def load(workspace: str) -> str:
    """Return the contents of context.md, or '' if not yet generated."""
    from . import store
    path = store.context_path(workspace)
    try:
        return Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
