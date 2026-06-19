"""CancellationToken — interruptible sleeps and cross-process stop detection.

The token reads stop_requested and paused from the state JSON file on every
poll interval.  Cross-process signalling (CLI pause/stop → running loop)
works because both processes share the same file.  Polling keeps the latency
under POLL_INTERVAL seconds regardless of what the loop is doing.
"""
from __future__ import annotations

import json
import time

POLL_INTERVAL = 5.0  # maximum seconds between state-file reads


class CancellationToken:
    """Interruptible wait with cross-process stop/pause detection.

    Create one per loop session and pass it to runner.run() and any
    long-running sleep.

    Example::

        token = CancellationToken(state_path)

        # Interruptible 1800-second rate-limit sleep:
        stopped = token.wait(1800)

        # Cheap inline check (reads file at most every POLL_INTERVAL s):
        if token.is_stop_requested():
            break
    """

    __slots__ = ("_path", "_last_read", "_stop", "_paused")

    def __init__(self, state_path: str) -> None:
        self._path = state_path
        self._last_read: float = 0.0
        self._stop: bool = False
        self._paused: bool = False

    # ── private ───────────────────────────────────────────────────────────────

    def _refresh(self, *, force: bool = False) -> None:
        """Read flags from disk if POLL_INTERVAL has elapsed (or forced)."""
        now = time.monotonic()
        if not force and now - self._last_read < POLL_INTERVAL:
            return
        self._last_read = now
        try:
            with open(self._path) as f:
                data = json.load(f)
            self._stop = bool(data.get("stop_requested", False))
            self._paused = bool(data.get("paused", False))
        except Exception:
            pass  # stale cache is safer than crashing

    # ── public ────────────────────────────────────────────────────────────────

    def is_stop_requested(self) -> bool:
        """Check (reading disk at most every POLL_INTERVAL s)."""
        self._refresh()
        return self._stop

    def is_paused(self) -> bool:
        """Check (reading disk at most every POLL_INTERVAL s)."""
        self._refresh()
        return self._paused

    def wait(self, total_seconds: float) -> bool:
        """Interruptible sleep for up to total_seconds.

        Wakes early and returns True  if stop_requested is found.
        Returns False when the full timeout elapses without a stop request.

        Raises nothing — errors in reading the state file are silently ignored
        so that a corrupted state file cannot permanently stall the loop.
        """
        deadline = time.monotonic() + total_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(POLL_INTERVAL, remaining))
            self._refresh(force=True)
            if self._stop:
                return True
