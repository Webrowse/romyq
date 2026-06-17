import subprocess
import time

from prompts import build_claude_prompt


LIMIT_STRINGS = [
    "usage limit",
    "rate limit",
    "quota",
    "try again later",
    "too many requests",
    "monthly usage limit",
    "credit balance is too low",
]


class ClaudeRateLimit(Exception):
    pass


def check_rate_limit(
    stdout: str,
    stderr: str,
) -> None:
    text = (
        f"{stdout}\n{stderr}"
    ).lower()

    for phrase in LIMIT_STRINGS:
        if phrase in text:
            raise ClaudeRateLimit(
                phrase
            )


def run_claude(
    workspace: str,
    task: str,
) -> subprocess.CompletedProcess:
    prompt = build_claude_prompt(
        task
    )

    result = subprocess.run(
        [
            "claude",
            "-p",
            "--dangerously-skip-permissions",
            prompt,
        ],
        cwd=workspace,
        capture_output=True,
        text=True,
    )

    check_rate_limit(
        result.stdout,
        result.stderr,
    )

    return result


def run_claude_with_retry(
    workspace: str,
    task: str,
    sleep_seconds: int = 1800,
) -> subprocess.CompletedProcess:
    while True:
        try:
            return run_claude(
                workspace=workspace,
                task=task,
            )

        except ClaudeRateLimit as e:
            print(
                "\nClaude usage limit reached."
            )

            print(
                f"Matched: {e}"
            )

            print(
                f"Sleeping for "
                f"{sleep_seconds} seconds..."
            )

            time.sleep(
                sleep_seconds
            )
