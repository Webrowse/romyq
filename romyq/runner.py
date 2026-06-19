from __future__ import annotations

import re
import subprocess
import threading
import time
from datetime import datetime, timedelta, timezone

from . import activity


# ── rate-limit detection ──────────────────────────────────────────────────────

# Specific Claude session-limit message:
# "You've hit your session limit · resets 5:50am (Asia/Calcutta)"
_SESSION_LIMIT_RE = re.compile(
    r"you(?:'ve| have) hit your session limit",
    re.IGNORECASE,
)

# Extracts "5:50am" and optional "Asia/Calcutta" from the session-limit line.
_RESET_TIME_RE = re.compile(
    r"resets?\s+(\d{1,2}:\d{2}\s*(?:am|pm)?)\s*(?:\(([^)]+)\))?",
    re.IGNORECASE,
)

# Safety margin added to the parsed reset time before sleeping.
_RESET_BUFFER_MINUTES = 5

# Default sleep when the reset time cannot be parsed.
_DEFAULT_WAIT_SECONDS = 30 * 60  # 30 minutes


class ClaudeRateLimitError(Exception):
    """Raised when Claude's output signals that a rate / session limit has been hit.

    Attributes:
        reset_at      UTC datetime to wake up (includes _RESET_BUFFER_MINUTES).
                      None when the reset time could not be parsed.
        tz_name       Timezone name as reported by Claude, e.g. "Asia/Calcutta".
        reset_display Human-readable reset time extracted from the message, e.g. "5:50am".
    """

    def __init__(
        self,
        message: str,
        reset_at: datetime | None = None,
        tz_name: str | None = None,
        reset_display: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reset_at = reset_at
        self.tz_name = tz_name
        self.reset_display = reset_display


# Keep the old name as an alias so existing code that catches RateLimitError
# still works without changes.
RateLimitError = ClaudeRateLimitError


class ClaudeTimeoutError(Exception):
    pass


# ── reset-time parsing ────────────────────────────────────────────────────────

def _parse_reset_time(text: str) -> tuple[datetime | None, str | None, str | None]:
    """Parse a reset time from Claude's session-limit message.

    Returns:
        (utc_wake_time, tz_name, display_string)
        utc_wake_time includes _RESET_BUFFER_MINUTES safety margin.
        All three are None when parsing fails.
    """
    m = _RESET_TIME_RE.search(text)
    if not m:
        return None, None, None

    time_str = m.group(1).strip()   # e.g. "5:50am"
    tz_name = m.group(2)            # e.g. "Asia/Calcutta"  (may be None)

    # Parse the clock time — try 12h with am/pm, then 24h.
    reset_time = None
    for fmt in ("%I:%M%p", "%I:%M %p", "%H:%M"):
        try:
            reset_time = datetime.strptime(time_str.upper(), fmt.upper()).time()
            break
        except ValueError:
            continue

    if reset_time is None:
        return None, tz_name, time_str

    # Resolve timezone.
    tz: datetime.tzinfo = timezone.utc
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(tz_name)
        except Exception:
            pass  # fall back to UTC

    # Construct the next occurrence of reset_time in the target timezone.
    now_in_tz = datetime.now(tz)
    reset_dt = datetime.combine(now_in_tz.date(), reset_time, tzinfo=tz)
    if reset_dt <= now_in_tz:
        reset_dt += timedelta(days=1)

    # Convert to UTC and add the safety buffer.
    reset_utc = reset_dt.astimezone(timezone.utc) + timedelta(minutes=_RESET_BUFFER_MINUTES)
    return reset_utc, tz_name, time_str


# ── rate-limit check (called after Claude exits) ──────────────────────────────

def _check_rate_limit(stdout: str, stderr: str) -> None:
    """Raise ClaudeRateLimitError if the combined output signals a rate limit.

    Only the specific Claude session-limit message is detected.  Generic
    phrases such as "rate limit" and "usage limit" are intentionally NOT
    matched — they appear legitimately in code that Claude writes (e.g. a
    web service implementing its own rate limiter) and produce false positives
    that put the loop into a 30-minute sleep on every iteration.
    """
    combined = f"{stdout}\n{stderr}"
    if _SESSION_LIMIT_RE.search(combined):
        reset_at, tz_name, reset_display = _parse_reset_time(combined)
        raise ClaudeRateLimitError(
            "Claude session limit reached",
            reset_at=reset_at,
            tz_name=tz_name,
            reset_display=reset_display,
        )


# ── streaming helpers ─────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[^a-zA-Z]*[a-zA-Z]")
_STREAM_INTERVAL = 2.0


def _filter_stream(raw: str) -> str | None:
    clean = _ANSI_RE.sub("", raw).strip()
    if not clean:
        return None
    if len(clean) > 150:
        return None
    if clean[0] in ("{", "[", "`"):
        return None
    if raw.startswith("\t") or raw.startswith("    "):
        return None
    return clean[:97] + "..." if len(clean) > 100 else clean


def _drain(stream, buf: list, on_line=None) -> None:
    try:
        for line in iter(stream.readline, ""):
            buf.append(line)
            if on_line:
                on_line(line)
    finally:
        stream.close()


def _terminate(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


# ── engineer prompt ───────────────────────────────────────────────────────────

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


# ── run ───────────────────────────────────────────────────────────────────────

def run(
    workspace: str,
    task: str,
    on_heartbeat=None,
    timeout_seconds: int = DEFAULT_TIMEOUT,
) -> subprocess.CompletedProcess:
    """Run Claude on a task.

    Raises:
        ClaudeRateLimitError  when Claude's output signals a session/usage limit.
        ClaudeTimeoutError    when the process exceeds timeout_seconds.
    """
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

    last_stream: list[float] = [0.0]

    def _on_stdout_line(raw: str) -> None:
        now = time.monotonic()
        if now - last_stream[0] < _STREAM_INTERVAL:
            return
        display = _filter_stream(raw)
        if display:
            activity.log(f"[Claude] {display}")
            last_stream[0] = now

    t_out = threading.Thread(target=_drain, args=(proc.stdout, stdout_buf, _on_stdout_line), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc.stderr, stderr_buf), daemon=True)
    t_out.start()
    t_err.start()

    start = time.monotonic()
    next_beat = 10

    while proc.poll() is None:
        time.sleep(1)
        elapsed = int(time.monotonic() - start)

        if elapsed >= timeout_seconds:
            activity.log(f"Claude timed out after {elapsed}s ({timeout_seconds}s limit) — terminating.")
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
