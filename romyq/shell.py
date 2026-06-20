"""Live operator shell — REPL for project management commands.

Run `romyq shell` in a terminal alongside a running `romyq run` session.

Builtin commands:
  status            Show loop state and current task
  roadmap           Show lifecycle roadmap with progress bars
  phase             Show current phase and its tasks
  capabilities      Show project capability model
  readiness         Show readiness score
  recommendation    Show Continue/Pause/Review/Stop recommendation
  pause             Request loop pause after current task
  resume            Resume a paused loop
  stop              Request graceful loop shutdown
  rules             List active project rules
  knowledge         Show knowledge base summary
  help              Show this help
  exit / quit       Exit the shell

Free-text instructions are recorded as steering notes and picked up by
the planner on the next loop iteration.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable, TextIO

BUILTIN_COMMANDS = frozenset({
    "status", "roadmap", "phase", "capabilities", "readiness",
    "recommendation", "pause", "resume", "stop", "rules", "knowledge",
    "help", "exit", "quit", "dashboard",
})

_HELP = """
  status          — current task, phase, loop state
  roadmap         — lifecycle roadmap with progress bars
  phase           — current phase and its tasks
  capabilities    — project capability model
  readiness       — mission readiness score
  recommendation  — Continue / Pause / Review / Stop
  pause           — pause after the current task
  resume          — resume a paused loop
  stop            — graceful shutdown
  rules           — list active project rules
  knowledge       — knowledge base summary
  dashboard       — full lifecycle-first overview
  exit / quit     — exit this shell

  Any other text is recorded as a steering instruction.
  Example: use PostgreSQL
           require JWT authentication
"""


# ── command parsing ───────────────────────────────────────────────────────────

def parse_command(line: str) -> tuple[str, list[str]]:
    """Split a shell line into (command, args). Returns ('', []) for empty input."""
    line = line.strip()
    if not line:
        return "", []
    parts = line.split(None, 1)
    cmd = parts[0].lower()
    rest = parts[1].split() if len(parts) > 1 else []
    return cmd, rest


def is_builtin(line: str) -> bool:
    """Return True if the first word of *line* is a builtin command."""
    cmd, _ = parse_command(line)
    return cmd in BUILTIN_COMMANDS


# ── per-command handlers ──────────────────────────────────────────────────────

def _cmd_status(workspace: str, out: TextIO) -> None:
    from . import store
    from .state import load as load_state
    try:
        state = load_state(store.state_path(workspace))
    except Exception:
        print("  No state found.", file=out)
        return
    W = 18
    def row(k, v): print(f"  {k:<{W}}{v}", file=out)
    row("Status:", state.get("status", "unknown"))
    row("Phase:", state.get("phase", "idle"))
    row("Tasks complete:", str(state.get("tasks_completed", 0)))
    row("Last commit:", state.get("last_commit") or "(none)")
    task = state.get("current_task", "")
    if task:
        row("Current task:", task.replace("\n", " ")[:70] + "…")


def _cmd_roadmap(workspace: str, out: TextIO) -> None:
    from . import store
    from .lifecycle import load as lc_load, format_roadmap
    from .viz import format_phase_bars, format_overall_bar
    lc = lc_load(store.lifecycle_path(workspace))
    if not lc.get("phases"):
        print("  No lifecycle found.", file=out)
        return
    print(format_phase_bars(lc), file=out)
    print(file=out)
    print(format_overall_bar(lc), file=out)


def _cmd_phase(workspace: str, out: TextIO) -> None:
    from . import store
    from .lifecycle import load as lc_load, format_current_phase
    lc = lc_load(store.lifecycle_path(workspace))
    if not lc.get("phases"):
        print("  No lifecycle found.", file=out)
        return
    print(format_current_phase(lc), file=out)


def _cmd_capabilities(workspace: str, out: TextIO) -> None:
    from . import store
    from .capabilities import format_capabilities, list_capabilities
    ps_path = store.project_state_path(workspace)
    caps = list_capabilities(ps_path)
    if caps:
        print(format_capabilities(ps_path), file=out)
    else:
        print("  No capabilities tracked yet.", file=out)


def _cmd_readiness(workspace: str, out: TextIO) -> None:
    from . import store
    from .readiness import compute_from_path, format_readiness
    rdns = compute_from_path(store.project_state_path(workspace))
    print(format_readiness(rdns), file=out)


def _cmd_recommendation(workspace: str, out: TextIO) -> None:
    from .recommendation import recommend_from_paths, format_recommendation
    result = recommend_from_paths(workspace_path=workspace)
    print(format_recommendation(result), file=out)


def _cmd_pause(workspace: str, out: TextIO) -> None:
    from . import store
    from .state import load as load_state, save as save_state
    s_path = store.state_path(workspace)
    try:
        state = load_state(s_path)
        if state.get("paused"):
            print("  Already paused.", file=out)
            return
        state["paused"] = True
        save_state(state, s_path)
        print("  PAUSE REQUEST RECEIVED — loop will pause after current task.", file=out)
    except Exception as e:
        print(f"  Error: {e}", file=out)


def _cmd_resume(workspace: str, out: TextIO) -> None:
    from . import store
    from .state import load as load_state, save as save_state
    s_path = store.state_path(workspace)
    try:
        state = load_state(s_path)
        if not state.get("paused"):
            print("  Not paused.", file=out)
            return
        state["paused"] = False
        save_state(state, s_path)
        print("  RESUME REQUEST RECEIVED — loop will continue.", file=out)
    except Exception as e:
        print(f"  Error: {e}", file=out)


def _cmd_stop(workspace: str, out: TextIO) -> None:
    from . import store
    from .state import load as load_state, save as save_state
    s_path = store.state_path(workspace)
    try:
        state = load_state(s_path)
        if state.get("stop_requested"):
            print("  Stop already requested.", file=out)
            return
        state["stop_requested"] = True
        save_state(state, s_path)
        print("  STOP REQUEST RECEIVED — loop will exit after current task.", file=out)
    except Exception as e:
        print(f"  Error: {e}", file=out)


def _cmd_rules(workspace: str, out: TextIO) -> None:
    from . import store
    from .rules import format_rules, list_rules
    r_path = store.rules_path(workspace)
    active = list_rules(r_path)
    if active:
        print(format_rules(r_path), file=out)
    else:
        print("  No rules defined.", file=out)


def _cmd_knowledge(workspace: str, out: TextIO) -> None:
    from . import store
    from . import knowledge as know_mod
    know_path = store.knowledge_path(workspace)
    data = know_mod.load(know_path)
    lessons = data.get("lessons", [])
    if lessons:
        for i, l in enumerate(lessons[:5], 1):
            print(f"  {i}. {l}", file=out)
        if len(lessons) > 5:
            print(f"  … ({len(lessons) - 5} more)", file=out)
    else:
        print("  No lessons recorded yet.", file=out)


def _cmd_dashboard(workspace: str, out: TextIO) -> None:
    from .dashboard import render
    render(workspace, out=out)


def _record_instruction(workspace: str, text: str, out: TextIO) -> None:
    """Record a free-text steering instruction."""
    try:
        from . import store, notes as notes_mod
        notes_mod.append(store.notes_path(workspace), text)
        print(f"  Instruction recorded: {text}", file=out)
    except Exception as e:
        print(f"  Failed to record: {e}", file=out)


# ── dispatcher ────────────────────────────────────────────────────────────────

_DISPATCH: dict[str, Callable] = {
    "status": _cmd_status,
    "roadmap": _cmd_roadmap,
    "phase": _cmd_phase,
    "capabilities": _cmd_capabilities,
    "readiness": _cmd_readiness,
    "recommendation": _cmd_recommendation,
    "pause": _cmd_pause,
    "resume": _cmd_resume,
    "stop": _cmd_stop,
    "rules": _cmd_rules,
    "knowledge": _cmd_knowledge,
    "dashboard": _cmd_dashboard,
}


def dispatch(line: str, workspace: str, *, out: TextIO | None = None) -> bool:
    """Execute a shell command. Returns False if the shell should exit."""
    if out is None:
        out = sys.stdout

    cmd, _ = parse_command(line)

    if not cmd:
        return True

    if cmd in ("exit", "quit"):
        return False

    if cmd == "help":
        print(_HELP, file=out)
        return True

    if cmd in _DISPATCH:
        try:
            _DISPATCH[cmd](workspace, out)
        except Exception as e:
            print(f"  Error: {e}", file=out)
        return True

    # Free-text instruction
    _record_instruction(workspace, line.strip(), out)
    return True


# ── REPL ─────────────────────────────────────────────────────────────────────

def run_shell(
    workspace_path: str,
    *,
    _input_fn: Callable[[str], str] | None = None,
    out: TextIO | None = None,
) -> None:
    """Run the operator shell REPL until 'exit', 'quit', or EOF."""
    if out is None:
        out = sys.stdout
    if _input_fn is None:
        _input_fn = input

    print(file=out)
    print("  Romyq Operator Shell", file=out)
    print("  Type 'help' for commands, 'exit' to quit.", file=out)
    print("  Free text is recorded as steering instructions.", file=out)
    print(file=out)

    while True:
        try:
            line = _input_fn("> ")
        except (EOFError, KeyboardInterrupt):
            print(file=out)
            break

        if not dispatch(line, workspace_path, out=out):
            break
