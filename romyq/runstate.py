"""RunState enum and transition table for the Romyq autonomous loop.

State diagram (simplified):

    IDLE ──► PLANNING ──► EXECUTING ──► VALIDATING ──► IDLE
              │               │              │
              ▼               ▼              ▼
            PAUSED         RATE_LIMITED   FAILED
              │               │              │
              └──────────────►└──────────────►PLANNING
                                             │
                                          STOPPING ──► STOPPED

Any state can transition to STOPPING or STOPPED (emergency exit path).
"""
from __future__ import annotations

import sys
from enum import Enum


class RunState(str, Enum):
    """Fine-grained execution phase of the autonomous loop.

    Stored in state.json["phase"].  Inherits from str so values serialise
    directly as JSON strings without extra conversion.
    """

    IDLE = "idle"               # between tasks — ready to plan next
    PLANNING = "planning"       # asking DeepSeek for a task
    EXECUTING = "executing"     # Claude subprocess is running
    VALIDATING = "validating"   # validator is checking the result
    PAUSED = "paused"           # loop is idle — waiting for romyq resume
    RATE_LIMITED = "rate_limited"  # sleeping until Claude session resets
    STOPPING = "stopping"       # stop requested — finishing current work
    STOPPED = "stopped"         # loop has exited
    FAILED = "failed"           # repeated failures, human review needed


# ── transition table ──────────────────────────────────────────────────────────
# Maps each state to the set of states it can transition into.
# STOPPING and STOPPED are reachable from every state (emergency exit).

_EMERGENCY = frozenset({RunState.STOPPING, RunState.STOPPED})

TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.IDLE:         frozenset({RunState.PLANNING, RunState.PAUSED}) | _EMERGENCY,
    RunState.PLANNING:     frozenset({RunState.EXECUTING, RunState.PAUSED}) | _EMERGENCY,
    RunState.EXECUTING:    frozenset({RunState.VALIDATING, RunState.RATE_LIMITED}) | _EMERGENCY,
    RunState.VALIDATING:   frozenset({RunState.IDLE, RunState.FAILED, RunState.PAUSED}) | _EMERGENCY,
    RunState.PAUSED:       frozenset({RunState.IDLE, RunState.PLANNING}) | _EMERGENCY,
    RunState.RATE_LIMITED: frozenset({RunState.IDLE, RunState.PLANNING}) | _EMERGENCY,
    RunState.STOPPING:     frozenset({RunState.STOPPED}),
    RunState.STOPPED:      frozenset(),        # terminal
    RunState.FAILED:       frozenset({RunState.PLANNING}) | _EMERGENCY,
}


def is_valid_transition(from_state: str | RunState, to_state: str | RunState) -> bool:
    """Return True if the transition from_state → to_state is allowed."""
    try:
        fs = RunState(from_state) if not isinstance(from_state, RunState) else from_state
        ts = RunState(to_state) if not isinstance(to_state, RunState) else to_state
    except ValueError:
        return True  # unknown state strings are not our problem — allow
    return ts in TRANSITIONS.get(fs, frozenset())


def coerce(value: str, default: RunState = RunState.IDLE) -> RunState:
    """Safely convert a string to RunState, returning default on failure."""
    try:
        return RunState(value)
    except ValueError:
        return default
