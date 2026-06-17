import subprocess


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


def inspect_repository(workspace: str) -> dict:
    return {
        "git_log": git_log(workspace),
        "git_status": git_status(workspace),
        "latest_commit": latest_commit(workspace),
        "diff_stat": diff_stat(workspace),
    }
