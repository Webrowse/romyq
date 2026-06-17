import subprocess
from pathlib import Path


ROOT_FILES = [
    "Cargo.toml",
    "package.json",
    "pyproject.toml",
    "requirements.txt",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.yaml",
    "README.md",
]


# ── bootstrap ────────────────────────────────────────────────────────────────

def _is_git_repo(workspace: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _has_commits(workspace: str) -> bool:
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    return bool(result.stdout.strip())


def bootstrap(workspace: str) -> None:
    path = Path(workspace)
    path.mkdir(parents=True, exist_ok=True)

    if not _is_git_repo(workspace):
        subprocess.run(["git", "init"], cwd=workspace, capture_output=True)
        print(f"Initialized git repository in {workspace}/")

    if not _has_commits(workspace):
        gitignore = path / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Romiq workspace\n")

        subprocess.run(["git", "add", ".gitignore"], cwd=workspace, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "chore: initial commit"],
            cwd=workspace,
            capture_output=True,
        )
        print(f"Created initial commit in {workspace}/")


# ── git inspection ────────────────────────────────────────────────────────────

def git_log(workspace: str) -> str:
    result = subprocess.run(
        ["git", "log", "--oneline", "-10"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def git_status(workspace: str) -> str:
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def latest_commit(workspace: str) -> str:
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def diff_stat(workspace: str) -> str:
    result = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def inspect(workspace: str) -> dict:
    return {
        "git_log": git_log(workspace),
        "git_status": git_status(workspace),
        "latest_commit": latest_commit(workspace),
        "diff_stat": diff_stat(workspace),
    }


# ── file / project inspection ─────────────────────────────────────────────────

def _detect_project_type(workspace: str) -> str:
    root = Path(workspace)

    if (root / "Cargo.toml").exists():
        return "rust"
    if (root / "package.json").exists():
        return "node"
    if (root / "pyproject.toml").exists():
        return "python"
    if (root / "requirements.txt").exists():
        return "python"
    if (root / "go.mod").exists():
        return "go"
    if (root / "pom.xml").exists():
        return "java"
    if (root / "build.gradle").exists():
        return "java"
    return "unknown"


def summary_text(workspace: str) -> str:
    root = Path(workspace)

    project_type = _detect_project_type(workspace)

    important = [
        name for name in ROOT_FILES if (root / name).exists()
    ]

    directories = sorted(
        item.name for item in root.iterdir() if item.is_dir()
    )

    files = sorted(
        item.name for item in root.iterdir() if item.is_file()
    )

    return (
        f"Project Type: {project_type}\n"
        f"Important Files: {', '.join(important) or 'none'}\n"
        f"Directories: {', '.join(directories) or 'none'}\n"
        f"Files: {', '.join(files) or 'none'}"
    )
