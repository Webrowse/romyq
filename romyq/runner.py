import subprocess
import time


_LIMIT_STRINGS = [
    "usage limit",
    "rate limit",
    "quota",
    "try again later",
    "too many requests",
    "monthly usage limit",
    "credit balance is too low",
]

_ENGINEER_PROMPT = """\
You are the engineer.

Repository is the source of truth.

Task:

{task}

Requirements:

- Implement only this task.
- Verify your changes.
- Commit your work.
- Do not perform unrelated work.
- Do not refactor unrelated code.
- Keep changes minimal and focused.
- Ensure the repository is left clean.
- Print COMPLETED when finished.

If task cannot be completed, explain why.
"""


class RateLimitError(Exception):
    pass


def _check_rate_limit(stdout: str, stderr: str) -> None:
    text = f"{stdout}\n{stderr}".lower()
    for phrase in _LIMIT_STRINGS:
        if phrase in text:
            raise RateLimitError(phrase)


def run(workspace: str, task: str) -> subprocess.CompletedProcess:
    prompt = _ENGINEER_PROMPT.format(task=task)

    result = subprocess.run(
        ["claude", "-p", "--dangerously-skip-permissions", prompt],
        cwd=workspace,
        capture_output=True,
        text=True,
    )

    _check_rate_limit(result.stdout, result.stderr)
    return result


def run_with_retry(workspace: str, task: str, sleep_seconds: int = 1800) -> subprocess.CompletedProcess:
    while True:
        try:
            return run(workspace=workspace, task=task)
        except RateLimitError as e:
            print(f"\nClaude rate limit reached ({e}). Sleeping {sleep_seconds}s...")
            time.sleep(sleep_seconds)
