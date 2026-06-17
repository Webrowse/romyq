import re
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

DEFAULT_TIMEOUT = 30 * 60  # 30 minutes

# Matches standard ANSI CSI escape sequences (colours, cursor movement, etc.)
_ANSI_RE = re.compile(r"\x1b\[[^a-zA-Z]*[a-zA-Z]")

# Minimum seconds between streamed [Claude] lines — prevents terminal flood
_STREAM_INTERVAL = 2.0


class RateLimitError(Exception):
    pass


class ClaudeTimeoutError(Exception):
    pass


def _check_rate_limit(stdout: str, stderr: str) -> None:
    text = f"{stdout}\n{stderr}".lower()
    for phrase in _LIMIT_STRINGS:
        if phrase in text:
            raise RateLimitError(phrase)


def _filter_stream(raw: str) -> str | None:
    """Return a printable version of raw, or None if the line should be skipped.

    Skips: blank lines, ANSI-only lines, lines > 150 chars (code / JSON dumps),
    lines that start with JSON delimiters or code-fence markers, and
    tab/4-space-indented code blocks.
    """
    clean = _ANSI_RE.sub("", raw).strip()

    if not clean:
        return None
    if len(clean) > 150:
        return None
    if clean[0] in ("{", "[", "`"):
        return None
    if raw.startswith("\t") or raw.startswith("    "):
        return None

    # Truncate lines that are long-ish but passed the 150-char gate
    if len(clean) > 100:
        return clean[:97] + "..."
    return clean


def _drain(stream, buf: list, on_line=None) -> None:
    try:
        for line in iter(stream.readline, ""):
            buf.append(line)
            if on_line:
                on_line(line)
    finally:
        stream.close()


def _terminate(proc: subprocess.Popen) -> None:
    """Send SIGTERM, escalate to SIGKILL if the process does not exit within 5s."""
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run(
    workspace: str,
    task: str,
    on_heartbeat=None,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess:
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

    # Rate-limited stdout streaming — one [Claude] line every _STREAM_INTERVAL seconds
    last_stream: list[float] = [0.0]

    def _on_stdout_line(raw: str) -> None:
        now = time.monotonic()
        if now - last_stream[0] < _STREAM_INTERVAL:
            return
        display = _filter_stream(raw)
        if display:
            activity.log(f"[Claude] {display}")
            last_stream[0] = now

    t_out = threading.Thread(
        target=_drain, args=(proc.stdout, stdout_buf, _on_stdout_line), daemon=True
    )
    t_err = threading.Thread(
        target=_drain, args=(proc.stderr, stderr_buf), daemon=True
    )
    t_out.start()
    t_err.start()

    start = time.monotonic()
    next_beat = 10

    while proc.poll() is None:
        time.sleep(1)
        elapsed = int(time.monotonic() - start)

        if elapsed >= timeout_seconds:
            activity.log(
                f"Claude timed out after {elapsed}s ({timeout_seconds}s limit) — terminating."
            )
            _terminate(proc)
            t_out.join(timeout=3)
            t_err.join(timeout=3)
            raise ClaudeTimeoutError(f"exceeded {timeout_seconds}s")

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
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess:
    while True:
        try:
            return run(
                workspace=workspace,
                task=task,
                on_heartbeat=on_heartbeat,
                timeout_seconds=timeout_seconds,
            )
        except RateLimitError as e:
            activity.log(f"Claude rate limit ({e}) — sleeping {sleep_seconds}s")
            time.sleep(sleep_seconds)
        except ClaudeTimeoutError as e:
            return subprocess.CompletedProcess(
                args=["claude"],
                returncode=1,
                stdout="",
                stderr=f"Claude timed out: {e}",
            )
