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


# ── bootstrap ─────────────────────────────────────────────────────────────────

def is_git_repo(path: str) -> bool:
    r = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=path, capture_output=True,
    )
    return r.returncode == 0


def has_commits(path: str) -> bool:
    r = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=path, capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def bootstrap(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)

    if not is_git_repo(path):
        subprocess.run(["git", "init"], cwd=path, capture_output=True)
        print(f"Initialized git repository in {path}/")

    if not has_commits(path):
        gitignore = Path(path) / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("# Romyq workspace\n")

        subprocess.run(["git", "add", ".gitignore"], cwd=path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "chore: initial commit"],
            cwd=path, capture_output=True,
        )
        print(f"Created initial commit in {path}/")


# ── git inspection ────────────────────────────────────────────────────────────

def git_log(path: str) -> str:
    r = subprocess.run(
        ["git", "log", "--oneline", "-10"],
        cwd=path, capture_output=True, text=True,
    )
    return r.stdout.strip()


def git_status(path: str) -> str:
    r = subprocess.run(
        ["git", "status", "--short"],
        cwd=path, capture_output=True, text=True,
    )
    return r.stdout.strip()


def latest_commit(path: str) -> str:
    r = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=path, capture_output=True, text=True,
    )
    return r.stdout.strip()


def diff_stat(path: str) -> str:
    r = subprocess.run(
        ["git", "diff", "--stat"],
        cwd=path, capture_output=True, text=True,
    )
    return r.stdout.strip()


def inspect(path: str) -> dict:
    if not Path(path).is_dir():
        return {"git_log": "", "git_status": "", "latest_commit": "", "diff_stat": ""}
    return {
        "git_log": git_log(path),
        "git_status": git_status(path),
        "latest_commit": latest_commit(path),
        "diff_stat": diff_stat(path),
    }


# ── file / project summary ────────────────────────────────────────────────────

def _project_type(path: str) -> str:
    root = Path(path)
    markers = [
        ("Cargo.toml", "rust"),
        ("package.json", "node"),
        ("pyproject.toml", "python"),
        ("requirements.txt", "python"),
        ("go.mod", "go"),
        ("pom.xml", "java"),
        ("build.gradle", "java"),
    ]
    for filename, lang in markers:
        if (root / filename).exists():
            return lang
    return "unknown"


def summary_text(path: str) -> str:
    root = Path(path)

    if not root.is_dir():
        return "Workspace does not exist."

    important = [name for name in ROOT_FILES if (root / name).exists()]
    directories = sorted(item.name for item in root.iterdir() if item.is_dir())
    files = sorted(item.name for item in root.iterdir() if item.is_file())

    return (
        f"Project Type: {_project_type(path)}\n"
        f"Important Files: {', '.join(important) or 'none'}\n"
        f"Directories: {', '.join(directories) or 'none'}\n"
        f"Files: {', '.join(files) or 'none'}"
    )
