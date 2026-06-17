import subprocess


def has_uncommitted_changes(workspace: str) -> bool:
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )

    return bool(result.stdout.strip())


def latest_commit(workspace: str) -> str:
    result = subprocess.run(
        ["git", "log", "--oneline", "-1"],
        cwd=workspace,
        capture_output=True,
        text=True,
    )

    return result.stdout.strip()


def commit_changed(
    before_commit: str,
    after_commit: str,
) -> bool:
    return before_commit != after_commit


def validate_task(
    workspace: str,
    before_commit: str,
    after_commit: str,
    claude_returncode: int,
) -> tuple[bool, str]:
    if claude_returncode != 0:
        return (
            False,
            "Claude exited with non-zero status",
        )

    if not commit_changed(
        before_commit,
        after_commit,
    ):
        return (
            False,
            "No new commit created",
        )

    if has_uncommitted_changes(workspace):
        return (
            False,
            "Repository left dirty",
        )

    return (
        True,
        "Validation passed",
    )
