import subprocess
from pathlib import Path


def is_git_repo(workspace: str) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )

    return result.returncode == 0


def has_commits(workspace: str) -> bool:
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )

    return bool(result.stdout.strip())


def bootstrap_workspace(workspace: str) -> None:
    path = Path(workspace)
    path.mkdir(parents=True, exist_ok=True)

    if not is_git_repo(workspace):
        subprocess.run(
            ["git", "init"],
            cwd=workspace,
            capture_output=True,
        )

        print(f"Initialized git repository in {workspace}/")

    if not has_commits(workspace):
        gitignore = path / ".gitignore"

        if not gitignore.exists():
            gitignore.write_text(
                "# Romiq workspace\n"
            )

        subprocess.run(
            ["git", "add", ".gitignore"],
            cwd=workspace,
            capture_output=True,
        )

        subprocess.run(
            ["git", "commit", "-m", "chore: initial commit"],
            cwd=workspace,
            capture_output=True,
        )

        print(f"Created initial commit in {workspace}/")
