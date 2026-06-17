import subprocess
import threading
import time

from . import activity


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


def _drain(stream, buf: list) -> None:
    try:
        for line in iter(stream.readline, ""):
            buf.append(line)
    finally:
        stream.close()


def run(workspace: str, task: str, on_heartbeat=None) -> subprocess.CompletedProcess:
    prompt = _ENGINEER_PROMPT.format(task=task)

    proc = subprocess.Popen(
        ["claude", "-p", "--dangerously-skip-permissions", prompt],
        cwd=workspace,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    stdout_buf: list[str] = []
    stderr_buf: list[str] = []
    t_out = threading.Thread(target=_drain, args=(proc.stdout, stdout_buf), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc.stderr, stderr_buf), daemon=True)
    t_out.start()
    t_err.start()

    start = time.monotonic()
    next_beat = 10

    while proc.poll() is None:
        time.sleep(1)
        elapsed = int(time.monotonic() - start)
        if elapsed >= next_beat:
            if on_heartbeat:
                on_heartbeat(elapsed)
            next_beat += 10

    t_out.join()
    t_err.join()

    stdout = "".join(stdout_buf)
    stderr = "".join(stderr_buf)

    _check_rate_limit(stdout, stderr)
    return subprocess.CompletedProcess(
        args=proc.args,
        returncode=proc.returncode,
        stdout=stdout,
        stderr=stderr,
    )


def run_with_retry(
    workspace: str,
    task: str,
    sleep_seconds: int = 1800,
    on_heartbeat=None,
) -> subprocess.CompletedProcess:
    while True:
        try:
            return run(workspace=workspace, task=task, on_heartbeat=on_heartbeat)
        except RateLimitError as e:
            activity.log(f"Claude rate limit ({e}) — sleeping {sleep_seconds}s")
            time.sleep(sleep_seconds)
