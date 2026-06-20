import argparse
import os
import shutil
import sys
from pathlib import Path

from . import __version__, notes as notes_mod, store
from .findings import unresolved as findings_unresolved
from .mission import create_template, exists as mission_exists, load as load_mission
from .workspace import bootstrap, is_git_repo, _ensure_gitignore_entry, detect, git_log
from .state import load as load_state, save as save_state
from .history import recent


def _resolve_workspace(args: argparse.Namespace, default: str = ".") -> str:
    return getattr(args, "workspace", None) or os.getenv("ROMYQ_WORKSPACE", default)


# ── init ──────────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> None:
    """Launch the interactive setup wizard."""
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    no_vcs = getattr(args, "no_vcs", False)
    skip_wizard = getattr(args, "no_wizard", False)

    if skip_wizard:
        # Legacy: non-interactive init (old behaviour)
        bootstrap(workspace_path)
        store.ensure_dir(workspace_path)
        created = create_template(str(root))
        if created:
            print("Created mission.md — edit it to describe what you want to build.")
        else:
            print("mission.md already exists.")
        print(f"\nWorkspace ready at: {root}/")
        print(f"State directory:    {root}/.romyq/")
        print("\nNext steps:")
        print("  1. Edit mission.md")
        print("  2. Set DEEPSEEK_API_KEY in .env or your environment")
        path_arg = f" {workspace_path}" if workspace_path != "." else ""
        print(f"  3. romyq run{path_arg}")
        return

    from .wizard import run_wizard
    run_wizard(workspace=str(root), no_vcs=no_vcs)


# ── attach ────────────────────────────────────────────────────────────────────

def cmd_attach(args: argparse.Namespace) -> None:
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    print(f"Attaching Romyq to: {root}\n")

    if not root.is_dir():
        print(f"Error: '{workspace_path}' is not a directory.")
        sys.exit(1)

    # Git check — warn but do not init and do not abort
    git_ok = is_git_repo(str(root))
    if not git_ok:
        print("  !  No git repository found at this path.")
        print("     Romyq uses git commits to track progress.")
        print("     Initialize one before running:")
        print(f"       cd {root}")
        print("       git init && git add -A && git commit -m 'initial commit'")
        print()

    # Create .romyq/ state directory
    romyq_dir = store.romyq_dir(str(root))
    already_existed = romyq_dir.exists()
    store.ensure_dir(str(root))
    if already_existed:
        print(f"  ✓  State directory  ({root}/.romyq/)  already exists")
    else:
        print(f"  ✓  State directory created  ({root}/.romyq/)")

    # Add .romyq/ to .gitignore without committing
    if git_ok:
        _ensure_gitignore_entry(str(root), ".romyq/")
        print(f"  ✓  .romyq/ added to .gitignore  (commit this change when ready)")

    # Create mission.md inside workspace if absent
    mission_path = root / "mission.md"
    created = create_template(str(root))
    if created:
        print(f"  ✓  Created mission.md  ({mission_path})")
    else:
        print(f"  ✓  mission.md already exists  ({mission_path})")

    print("\nNo git operations performed. Application code was not modified.")

    # Quick summary of what was detected
    d = detect(str(root))
    if d and d["language"] != "unknown":
        parts = [d["language"]]
        if d["frameworks"]:
            parts += d["frameworks"][:3]
        if d["test_framework"]:
            parts.append(d["test_framework"])
        print(f"\nDetected: {', '.join(parts)}")

    path_arg = f" {workspace_path}" if workspace_path != "." else ""
    print("\nNext steps:")
    print("  1. Edit mission.md — describe your goals for this project")
    print(f"  2. romyq info{path_arg}")
    print(f"  3. romyq run{path_arg}")


# ── note ──────────────────────────────────────────────────────────────────────

def cmd_note(args: argparse.Namespace) -> None:
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Error: workspace '{workspace_path}' not found. Run 'romyq init' or 'romyq attach' first.")
        sys.exit(1)

    message = args.message.strip()
    if not message:
        print("Error: note message cannot be empty.")
        sys.exit(1)

    path = store.notes_path(workspace_path)
    notes_mod.append(path, message)

    n = notes_mod.count(path)
    print(f"Note added ({n} total). Stored in {root}/.romyq/notes.md")


# ── info ──────────────────────────────────────────────────────────────────────

def cmd_info(args: argparse.Namespace) -> None:
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Error: '{workspace_path}' is not a directory.")
        sys.exit(1)

    print(f"romyq info: {root}\n")

    d = detect(str(root))
    if not d:
        print("  Could not read workspace.")
        sys.exit(1)

    W = 18  # label column width

    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    # Project
    row("Language:", d["language"])
    if d["frameworks"]:
        row("Frameworks:", ", ".join(d["frameworks"]))
    if d["dev_tools"]:
        row("Dev tools:", ", ".join(d["dev_tools"]))

    # Tests
    test_fw = d["test_framework"]
    test_detail = d["test_detail"]
    if test_fw and test_detail:
        row("Test suite:", f"{test_fw}  ({test_detail})")
    elif test_fw:
        row("Test suite:", test_fw)
    elif test_detail:
        row("Test suite:", test_detail)
    else:
        row("Test suite:", "none detected")

    # Build
    cmds = d["build_commands"]
    if cmds:
        row("Build:", cmds[0])
        for c in cmds[1:]:
            row("", c)

    # Repository
    branches = d["branches"]
    if branches:
        current = next((b for b in branches if b.startswith("*")), branches[0])
        others = [b for b in branches if not b.startswith("*")]
        row("Branch:", current.lstrip("* "))
        if others:
            row("Other branches:", ", ".join(b.strip() for b in others))

    if d["entry_points"]:
        row("Entry points:", ", ".join(d["entry_points"]))

    # Romyq state
    print()
    mission_path = Path("mission.md")
    if mission_path.exists():
        row("Mission:", f"✓  found  ({mission_path.resolve()})")
    else:
        row("Mission:", "✗  not set  (run 'romyq attach' or create mission.md)")

    romyq_dir = store.romyq_dir(str(root))
    if romyq_dir.exists():
        try:
            state = load_state(store.state_path(str(root)))
            tasks = state["tasks_completed"]
            status = state["status"]
            row("Tasks:", f"{tasks} completed  (status: {status})")
        except Exception:
            row("Tasks:", "0 completed")
        row("State dir:", f"✓  {root}/.romyq/")

        n_notes = notes_mod.count(store.notes_path(str(root)))
        if n_notes:
            note_lines = [
                l for l in notes_mod.load(store.notes_path(str(root))).splitlines()
                if l.strip().startswith("-")
            ]
            row("Notes:", f"{n_notes} note(s)")
            for line in note_lines[-3:]:
                row("", line.strip())
        else:
            row("Notes:", "none  (add with 'romyq note \"message\"')")
    else:
        row("Tasks:", "no history  (run 'romyq attach' first)")
        row("State dir:", f"✗  not attached")

    print()
    path_arg = f" {workspace_path}" if workspace_path != "." else ""
    if not romyq_dir.exists():
        print(f"  Run 'romyq attach{path_arg}' to set up Romyq for this repository.")
    else:
        print(f"  Run 'romyq run{path_arg}' to start.")


# ── run ───────────────────────────────────────────────────────────────────────

def cmd_run(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    workspace_path = _resolve_workspace(args)

    if not mission_exists():
        print("Error: mission.md not found. Run 'romyq init' or 'romyq attach' first.")
        sys.exit(1)

    from .loop import run
    run(
        workspace_path,
        until_complete=args.until_complete,
        approval_mode=getattr(args, "approval", False),
    )


# ── steer ─────────────────────────────────────────────────────────────────────

def cmd_steer(args: argparse.Namespace) -> None:
    """Record an operator instruction for the active loop."""
    workspace_path = _resolve_workspace(args)
    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)
    store.migrate(workspace_path)
    from .steering import record_instruction
    instruction = args.instruction.strip()
    if not instruction:
        print("Error: instruction cannot be empty.")
        sys.exit(1)
    record_instruction(store.events_path(workspace_path), instruction)
    print(f"Instruction recorded: {instruction}")


# ── status ────────────────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
    import json as _json
    from dotenv import load_dotenv
    load_dotenv()
    workspace_path = _resolve_workspace(args)

    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    try:
        state = load_state(store.state_path(workspace_path))
    except Exception:
        print("No state found. Has romyq been run yet?")
        sys.exit(1)

    if getattr(args, "json", False):
        print(_json.dumps(state, indent=2))
        return

    W = 18

    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    print(f"Workspace: {Path(workspace_path).resolve()}\n")
    row("Status:", state["status"])
    row("Phase:", state.get("phase", "idle"))
    row("Tasks completed:", str(state["tasks_completed"]))
    row("Last commit:", state["last_commit"] or "(none)")
    row("Heartbeat:", state["heartbeat"] or "(none)")
    row("Audit interval:", f"every {state['audit_interval']} tasks")

    # Persistent failure tracking
    attempts = state.get("current_task_attempts", 0)
    if attempts > 0:
        row("Task attempts:", f"{attempts} / {state.get('max_task_attempts', 3)}")
        if state.get("last_failure_reason"):
            row("Last failure:", state["last_failure_reason"][:80])
        if state.get("last_failure_timestamp"):
            row("Failed at:", state["last_failure_timestamp"])
    consec = state.get("consecutive_failures", 0)
    if consec > 0:
        row("Consec. failures:", str(consec))

    if state["current_task"]:
        task_preview = state["current_task"][:120].replace("\n", " ")
        row("Current task:", task_preview + "...")


# ── explain ───────────────────────────────────────────────────────────────────

def cmd_explain(args: argparse.Namespace) -> None:
    """Show the full diagnostic picture for the current loop state."""
    from dotenv import load_dotenv
    load_dotenv()
    workspace_path = _resolve_workspace(args)

    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    try:
        state = load_state(store.state_path(workspace_path))
    except Exception:
        print("No state found. Has romyq been run yet?")
        sys.exit(1)

    SEP = "─" * 56

    def section(title: str) -> None:
        print(f"\n{title}")
        print(SEP)

    print(f"romyq explain: {Path(workspace_path).resolve()}")

    section("Loop State")
    W = 20
    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    row("status", state.get("status", "unknown"))
    row("phase", state.get("phase", "idle"))
    row("heartbeat", state.get("heartbeat") or "(none)")
    row("tasks completed", str(state.get("tasks_completed", 0)))
    row("last commit", state.get("last_commit") or "(none)")

    if state.get("paused"):
        row("paused", "yes — run 'romyq resume' to continue")
    if state.get("stop_requested"):
        row("stop requested", "yes — loop will exit after current task")
    if state.get("resume_at"):
        row("rate limited", f"resumes at {state['resume_at']}")

    section("Current Task")
    task = state.get("current_task", "")
    if task:
        for line in task.splitlines():
            print(f"  {line}")
    else:
        print("  (none)")

    section("Failure Tracking")
    attempts = state.get("current_task_attempts", 0)
    ceiling = state.get("max_task_attempts", 3)
    consec = state.get("consecutive_failures", 0)
    task_key = state.get("current_task_key", "")
    row("task key", task_key or "(none)")
    row("attempts", f"{attempts} / {ceiling}" + (" — BLOCKED" if attempts >= ceiling and task_key else ""))
    row("consecutive failures", str(consec))
    if state.get("last_failure_reason"):
        row("last failure reason", state["last_failure_reason"])
    if state.get("last_failure_timestamp"):
        row("last failure at", state["last_failure_timestamp"])

    section("Last Validation Evidence")
    evidence = state.get("last_validation_evidence", [])
    if evidence:
        for line in evidence:
            print(f"  {line}")
    else:
        print("  (none recorded)")

    section("Recovery Guidance")
    from .recovery import analyze_recovery_state
    rec = analyze_recovery_state(state)
    sev_prefix = {"ok": "  ✓", "warning": "  !", "error": "  ✗"}.get(rec.severity, "  ?")
    print(f"{sev_prefix}  {rec.situation}")
    print(f"     {rec.recommendation}")

    section("Planner Loop Detection")
    from .health_checks import detect_planner_loops
    mem_path = store.memory_path(workspace_path)
    loop_warnings = detect_planner_loops(mem_path) if Path(mem_path).exists() else []
    if loop_warnings:
        for w in loop_warnings:
            print(f"  ! {w}")
    else:
        print("  No loops detected.")

    print()


# ── logs ──────────────────────────────────────────────────────────────────────

def cmd_logs(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()
    workspace_path = _resolve_workspace(args)

    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    entries = recent(limit=args.last, path=store.history_path(workspace_path))

    if not entries:
        print("No task history yet.")
        return

    for i, entry in enumerate(entries, 1):
        status = "✓" if entry["success"] else "✗"
        print(f"\n[{i}] {status} {entry['timestamp']}  mode={entry['mode']}")
        print(f"    commit: {entry['commit'] or '(none)'}")
        print(f"    reason: {entry['validation_reason']}")
        task_preview = entry["task"][:120].replace("\n", " ")
        print(f"    task:   {task_preview}")


# ── doctor ────────────────────────────────────────────────────────────────────

def cmd_doctor(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    ok = True

    def check(label: str, passed: bool, detail: str = "") -> None:
        nonlocal ok
        mark = "✓" if passed else "✗"
        line = f"  {mark}  {label}"
        if detail:
            line += f"  ({detail})"
        print(line)
        if not passed:
            ok = False

    print("romyq doctor\n")

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    check("DEEPSEEK_API_KEY", bool(api_key), "set" if api_key else "missing — add to .env")

    claude_bin = shutil.which("claude")
    check("claude CLI", bool(claude_bin), claude_bin or "not found in PATH")

    git_bin = shutil.which("git")
    check("git", bool(git_bin), git_bin or "not found in PATH — install git")

    mission_ok = mission_exists()
    check("mission.md", mission_ok, "found" if mission_ok else "missing — run 'romyq init' or 'romyq attach'")

    workspace_path = _resolve_workspace(args)
    workspace_exists = Path(workspace_path).exists()
    check(f"workspace ({workspace_path}/)", workspace_exists, "exists" if workspace_exists else "missing — run 'romyq init' or 'romyq attach'")

    if workspace_exists:
        git_ok = is_git_repo(workspace_path)
        check("workspace is a git repo", git_ok, "yes" if git_ok else "run 'romyq init' or 'git init'")

        romyq_dir = store.romyq_dir(workspace_path)
        check(
            f"state dir ({workspace_path}/.romyq/)",
            romyq_dir.exists(),
            "exists" if romyq_dir.exists() else "run 'romyq attach'",
        )

    print()
    if ok:
        print("All checks passed. Ready to run: romyq run")
    else:
        print("Some checks failed. Fix the issues above before running.")
        sys.exit(1)


# ── health ────────────────────────────────────────────────────────────────────

def cmd_health(args: argparse.Namespace) -> None:
    from datetime import datetime, timezone
    from dotenv import load_dotenv
    load_dotenv()

    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    W = 16

    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    print(f"romyq health: {root}\n")

    try:
        state = load_state(store.state_path(workspace_path))
    except Exception:
        print("  No state found. Has romyq been run yet?")
        return

    row("status", state["status"])

    # Task counts from full history
    all_entries = recent(limit=100000, path=store.history_path(workspace_path))
    n_passed = sum(1 for e in all_entries if e["success"])
    n_failed = len(all_entries) - n_passed
    tasks_str = f"{state['tasks_completed']} completed"
    if all_entries:
        tasks_str += f"  ({n_passed} passed / {n_failed} failed)"
    row("tasks", tasks_str)

    # Last commit
    row("last commit", state.get("last_commit") or "(none)")

    # Heartbeat age
    hb = state.get("heartbeat", "")
    if hb:
        try:
            hb_dt = datetime.fromisoformat(hb)
            age_s = int((datetime.now(timezone.utc) - hb_dt).total_seconds())
            if age_s < 60:
                age_str = f"{age_s}s ago"
            elif age_s < 3600:
                m, s = divmod(age_s, 60)
                age_str = f"{m}m {s:02d}s ago"
            else:
                h, r = divmod(age_s, 3600)
                age_str = f"{h}h {r // 60}m ago"
            if age_s > 1800:
                age_str += "  (process may have stopped)"
            row("heartbeat", age_str)
        except Exception:
            row("heartbeat", hb)
    else:
        row("heartbeat", "(none — not yet run)")

    # Phase
    row("phase", state.get("phase", "idle"))

    # Persistent failure tracking
    attempts = state.get("current_task_attempts", 0)
    consec = state.get("consecutive_failures", 0)
    if attempts > 0:
        ceiling = state.get("max_task_attempts", 3)
        row("task attempts", f"{attempts} / {ceiling}")
    if consec > 0:
        row("consec. failures", str(consec))
    if state.get("last_failure_reason"):
        reason_preview = state["last_failure_reason"][:60]
        row("last failure", reason_preview)

    # Findings
    f_items = findings_unresolved(store.findings_path(workspace_path))
    if f_items:
        _SEV = ["critical", "high", "medium", "low"]
        by_sev: dict[str, int] = {}
        for f in f_items:
            s = f.get("severity", "medium")
            by_sev[s] = by_sev.get(s, 0) + 1
        parts = [f"{by_sev[s]} {s}" for s in _SEV if s in by_sev]
        row("findings", f"{len(f_items)} unresolved  ({', '.join(parts)})")
    else:
        row("findings", "none")

    # Last task preview
    if state.get("current_task"):
        preview = state["current_task"].replace("\n", " ")
        if len(preview) > 100:
            preview = preview[:97] + "..."
        row("last task", preview)

    # Stuck-condition warnings
    from .health_checks import detect_stuck_conditions
    warnings = detect_stuck_conditions(
        state=state,
        history_path=store.history_path(workspace_path),
        events_path=store.events_path(workspace_path),
        memory_path=store.memory_path(workspace_path),
    )
    if warnings:
        print()
        print("  Warnings:")
        for w in warnings:
            print(f"  !  {w}")


# ── report ────────────────────────────────────────────────────────────────────

def cmd_report(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    SEP = "─" * 56

    def section(title: str) -> None:
        print(f"\n{title}")
        print(SEP)

    print(f"romyq report: {root}")

    # Mission
    section("Mission")
    try:
        mission_text = load_mission(str(root))
        lines = mission_text.strip().splitlines()
        for line in lines[:20]:
            print(f"  {line}")
        if len(lines) > 20:
            print(f"  ... ({len(lines) - 20} more lines)")
    except FileNotFoundError:
        print("  (mission.md not found — run 'romyq attach')")

    # Progress
    section("Progress")
    try:
        state = load_state(store.state_path(workspace_path))
        all_entries = recent(limit=100000, path=store.history_path(workspace_path))
        n_passed = sum(1 for e in all_entries if e["success"])
        n_failed = len(all_entries) - n_passed
        print(f"  status:    {state['status']}")
        print(f"  completed: {state['tasks_completed']} tasks"
              + (f"  ({n_passed} passed / {n_failed} failed)" if all_entries else ""))
    except Exception:
        print("  (romyq has not been run yet)")

    # Recent commits
    section("Recent Commits")
    commits = git_log(workspace_path)
    if commits:
        for line in commits.splitlines()[:8]:
            print(f"  {line}")
    else:
        print("  (no commits)")

    # Steering notes
    notes_text = notes_mod.load(store.notes_path(workspace_path))
    note_lines = [l for l in notes_text.splitlines() if l.strip().startswith("-")]
    if note_lines:
        section("Steering Notes")
        for line in note_lines:
            print(f"  {line.strip()}")

    # Findings
    section("Findings")
    f_items = findings_unresolved(store.findings_path(workspace_path))
    if f_items:
        _SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        for f in sorted(f_items, key=lambda x: _SEV_ORDER.get(x.get("severity", "medium"), 2)):
            sev = f.get("severity", "medium").upper()[:4]
            print(f"  [{sev:<4}]  {f['title'][:68]}")
    else:
        print("  No unresolved findings.")

    # Recent task history
    entries = recent(limit=5, path=store.history_path(workspace_path))
    if entries:
        section("Recent Tasks")
        for entry in reversed(entries):
            mark = "✓" if entry["success"] else "✗"
            ts = entry["timestamp"][:16].replace("T", " ")
            preview = entry["task"].replace("\n", " ")[:70]
            print(f"  {mark} [{ts}]  {preview}")

    # Recent events
    from .events import tail as events_tail
    evt_items = events_tail(store.events_path(workspace_path), n=10)
    if evt_items:
        section("Recent Events")
        for entry in evt_items:
            ts = entry.get("ts", "")[:19].replace("T", " ")
            evt = entry.get("event", "?")
            extras = {k: v for k, v in entry.items() if k not in ("ts", "event")}
            kv = "  ".join(f"{k}={v!r}" for k, v in extras.items()) if extras else ""
            print(f"  [{ts}] {evt}" + (f"  {kv}" if kv else ""))

    print()


# ── ui ────────────────────────────────────────────────────────────────────────

def cmd_ui(args: argparse.Namespace) -> None:
    try:
        from .ui import launch
    except ImportError:
        print("romyq ui requires the 'textual' library.")
        print()
        print("Install it with:")
        print("  pip install 'romyq[ui]'")
        print()
        print("Or install textual directly:")
        print("  pip install textual")
        sys.exit(1)

    workspace_path = _resolve_workspace(args)

    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    launch(workspace_path)


# ── events ───────────────────────────────────────────────────────────────────

def cmd_events(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()
    from .events import tail

    workspace_path = _resolve_workspace(args)
    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)
    e_path = store.events_path(workspace_path)
    events = tail(e_path, n=args.last)

    if not events:
        print("No events recorded yet.")
        return

    for entry in events:
        ts = entry.get("ts", "")[:19].replace("T", " ")
        evt = entry.get("event", "?")
        extras = {k: v for k, v in entry.items() if k not in ("ts", "event")}
        parts = [f"[{ts}] {evt}"]
        if extras:
            kv = "  ".join(f"{k}={v!r}" for k, v in extras.items())
            parts.append(f"  {kv}")
        print("".join(parts))


# ── pause / resume / stop ─────────────────────────────────────────────────────

def cmd_pause(args: argparse.Namespace) -> None:
    workspace_path = _resolve_workspace(args)
    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)
    s_path = store.state_path(workspace_path)
    state = load_state(s_path)
    if state.get("paused"):
        print("Already paused.")
        return
    state["paused"] = True
    save_state(state, s_path)
    print("PAUSE REQUEST RECEIVED")
    print("Waiting for safe checkpoint → loop will idle after current task.")
    print("Check status with: romyq status")
    print("Resume with:       romyq resume")
    try:
        from .events import emit as _emit
        from . import events as _ev
        _emit(store.events_path(workspace_path), _ev.PAUSE_CONFIRMED)
    except Exception:
        pass


def cmd_resume(args: argparse.Namespace) -> None:
    workspace_path = _resolve_workspace(args)
    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)
    s_path = store.state_path(workspace_path)
    state = load_state(s_path)
    if not state.get("paused"):
        print("Not paused.")
        return
    state["paused"] = False
    save_state(state, s_path)
    print("RESUME REQUEST RECEIVED")
    print("Loop will continue on the next iteration.")
    try:
        from .events import emit as _emit
        from . import events as _ev
        _emit(store.events_path(workspace_path), _ev.RESUME_CONFIRMED)
    except Exception:
        pass


def cmd_stop(args: argparse.Namespace) -> None:
    workspace_path = _resolve_workspace(args)
    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)
    s_path = store.state_path(workspace_path)
    state = load_state(s_path)
    if state.get("stop_requested"):
        print("Stop already requested.")
        return
    state["stop_requested"] = True
    save_state(state, s_path)
    print("STOP REQUEST RECEIVED")
    print("Loop will exit gracefully after the current task completes.")
    print("(If rate-limited and sleeping, it will wake early to honour the stop.)")
    try:
        from .events import emit as _emit
        from . import events as _ev
        _emit(store.events_path(workspace_path), _ev.STOP_CONFIRMED)
    except Exception:
        pass


# ── planning ──────────────────────────────────────────────────────────────────

def cmd_planning(args: argparse.Namespace) -> None:
    """Show the full planning context that would be injected into the next DeepSeek call."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    try:
        state = load_state(store.state_path(workspace_path))
    except Exception:
        state = {}

    from .context import load as ctx_load
    from .planning import build_planning_context
    from .health_checks import detect_planner_loops
    from .loop_detector import detect as detect_loops

    ctx_text = ctx_load(workspace_path)
    mem_path = store.memory_path(workspace_path)
    know_path = store.knowledge_path(workspace_path)

    planning_ctx = build_planning_context(
        state=state,
        findings_path=store.findings_path(workspace_path),
        history_path=store.history_path(workspace_path),
        context_text=ctx_text,
        memory_path=mem_path,
        knowledge_path=know_path,
    )

    loop_warnings = detect_planner_loops(mem_path) if Path(mem_path).exists() else []

    # Repeated-task warnings from memory
    from . import memory as mem_mod
    from . import knowledge as know_mod
    top_failed = mem_mod.most_failed(mem_path, limit=5) if Path(mem_path).exists() else []
    repeated = [(fp, cnt, preview) for fp, cnt, preview, _ in top_failed if cnt >= 2]

    # Memory signals
    sr = mem_mod.overall_success_rate(mem_path) if Path(mem_path).exists() else -1.0
    rr = mem_mod.retry_rate(mem_path) if Path(mem_path).exists() else 0.0
    avg_att = mem_mod.avg_attempts_per_task(mem_path) if Path(mem_path).exists() else 0.0

    # Knowledge signals
    know_data = know_mod.load(know_path)
    know_lessons = know_data.get("lessons", [])
    know_stale = know_mod.is_stale(know_path, mem_path, store.history_path(workspace_path), ctx_text)
    know_failures = know_mod.top_failure_patterns(know_path, limit=3)

    if getattr(args, "json", False):
        print(_json.dumps({
            "planning_context": planning_ctx,
            "repository_memory_available": bool(ctx_text),
            "planner_loops": loop_warnings,
            "repeated_task_warnings": [
                {"fp": fp, "count": cnt, "preview": preview}
                for fp, cnt, preview in repeated
            ],
            "blocked_task": {
                "key": state.get("current_task_key", ""),
                "attempts": state.get("current_task_attempts", 0),
                "ceiling": state.get("max_task_attempts", 3),
                "reason": state.get("last_failure_reason", ""),
            },
            "memory_signals": {
                "success_rate": sr,
                "retry_rate": rr,
                "avg_attempts_per_task": avg_att,
                "most_failed": [
                    {"fp": fp, "count": cnt, "preview": prev}
                    for fp, cnt, prev, _ in top_failed
                ],
            },
            "knowledge_signals": {
                "fresh": not know_stale,
                "lesson_count": len(know_lessons),
                "top_failure_patterns": know_failures,
            },
            "repository_signals": {
                "context_present": bool(ctx_text.strip()),
                "structure_hash": know_data.get("structure_hash", ""),
            },
        }, indent=2))
        return

    SEP = "─" * 56

    def section(title: str) -> None:
        print(f"\n{title}")
        print(SEP)

    print(f"romyq planning: {root}")

    section("Repository Memory")
    if ctx_text.strip():
        for line in ctx_text.strip().splitlines()[:25]:
            print(f"  {line}")
    else:
        print("  (not yet generated — run 'romyq learn')")

    section("Memory Signals")
    W = 26

    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    if sr >= 0:
        row("Success rate:", f"{sr * 100:.1f}%")
    else:
        row("Success rate:", "n/a")
    row("Retry rate:", f"{rr * 100:.1f}%")
    row("Avg attempts/task:", f"{avg_att:.2f}")
    if top_failed:
        fp0, cnt0, prev0, _ = top_failed[0]
        row("Most failed task:", f"[{cnt0}x] {prev0[:50]}")

    section("Knowledge Signals")
    row("Status:", "stale — will refresh on next run" if know_stale else f"fresh ({len(know_lessons)} lessons)")
    if know_failures:
        for p in know_failures:
            cnt = p.get("count", 0)
            prev = p.get("task_preview", "")[:55]
            print(f"  [{cnt}x] {prev}")
    else:
        row("Top failures:", "none")

    section("Repository Signals")
    row("Context present:", "yes" if ctx_text.strip() else "no — run 'romyq learn'")
    row("Knowledge hash:", know_data.get("structure_hash", "(none)") or "(none)")

    section("Planning Context")
    if planning_ctx:
        for line in planning_ctx.splitlines()[:60]:
            print(f"  {line}")
    else:
        print("  (nothing to inject — no failures or findings recorded yet)")

    section("Planner Loop Detection")
    if loop_warnings:
        for w in loop_warnings:
            print(f"  ! {w}")
    else:
        print("  No loops detected.")

    section("Repeated Task Warnings")
    if repeated:
        for fp, cnt, preview in repeated:
            print(f"  [{cnt}x] {preview[:70]}  (fp: {fp})")
    else:
        print("  None.")

    section("Blocked Task")
    key = state.get("current_task_key", "")
    attempts = state.get("current_task_attempts", 0)
    ceiling = state.get("max_task_attempts", 3)
    if key and attempts >= ceiling:
        print(f"  Key:      {key}")
        print(f"  Attempts: {attempts}/{ceiling} — BLOCKED")
        if state.get("last_failure_reason"):
            print(f"  Reason:   {state['last_failure_reason'][:120]}")
    else:
        print("  No blocked task.")

    print()


# ── memory ────────────────────────────────────────────────────────────────────

def cmd_memory(args: argparse.Namespace) -> None:
    """Show execution memory analysis: failures, blocked tasks, and loop detection."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from . import memory as mem_mod
    from .health_checks import detect_planner_loops

    mem_path = store.memory_path(workspace_path)
    mem_data = mem_mod.load(mem_path)
    entries = mem_data.get("entries", [])
    missions = mem_data.get("missions", {})

    total = len(entries)
    sr = mem_mod.overall_success_rate(mem_path)
    rr = mem_mod.retry_rate(mem_path)
    avg_att = mem_mod.avg_attempts_per_task(mem_path)
    top_failed = mem_mod.most_failed(mem_path, limit=10)
    loop_warnings = detect_planner_loops(mem_path)

    if getattr(args, "json", False):
        print(_json.dumps({
            "total_entries": total,
            "success_rate": sr,
            "retry_rate": rr,
            "avg_attempts_per_task": avg_att,
            "most_failed": [
                {"fp": fp, "count": cnt, "preview": prev, "last_reason": why}
                for fp, cnt, prev, why in top_failed
            ],
            "planner_loops": loop_warnings,
            "mission_outcomes": missions,
        }, indent=2))
        return

    SEP = "─" * 56

    def section(title: str) -> None:
        print(f"\n{title}")
        print(SEP)

    W = 24

    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    print(f"romyq memory: {root}")

    section("Summary")
    row("Total entries:", str(total))
    if sr >= 0:
        row("Success rate:", f"{sr * 100:.1f}%")
    else:
        row("Success rate:", "n/a (no entries)")
    row("Retry rate:", f"{rr * 100:.1f}%")
    row("Avg attempts/task:", f"{avg_att:.2f}")

    section("Most Failed Tasks")
    if top_failed:
        for i, (fp, cnt, preview, why) in enumerate(top_failed, 1):
            print(f"  {i}. [{cnt} failures]  {preview[:70]}")
            print(f"     fp: {fp}  last reason: {why[:60]}")
    else:
        print("  None.")

    section("Planner Loop Detection")
    if loop_warnings:
        for w in loop_warnings:
            print(f"  ! {w}")
    else:
        print("  No loops detected.")

    section("Mission Outcomes")
    if missions:
        for mfp, rec in missions.items():
            print(f"  {rec['preview'][:55]}")
            print(f"    total={rec['total']}  ok={rec['ok']}  blocked={rec['blocked']}")
    else:
        print("  No mission outcomes recorded.")

    print()


# ── plan ──────────────────────────────────────────────────────────────────────

def cmd_plan(args: argparse.Namespace) -> None:
    """Show the mission decomposition plan."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .decomposition import load_plan, format_plan, plan_summary

    p_path = store.plan_path(workspace_path)

    if getattr(args, "json", False):
        data = load_plan(p_path)
        print(_json.dumps(data, indent=2))
        return

    data = load_plan(p_path)
    if not data.get("generated_at"):
        print("No mission plan found.")
        print("Plans are generated automatically when 'romyq run' starts.")
        return

    SEP = "─" * 56
    print(f"romyq plan: {root}")
    print()
    summary = plan_summary(p_path)
    print(f"  Total tasks: {summary['total']}")
    print(f"  Completed:   {summary.get('completed', 0)}")
    print(f"  Pending:     {summary.get('pending', 0)}")
    print(f"  Active:      {summary.get('active', 0)}")
    print()
    print(SEP)
    print()
    print(format_plan(p_path))
    print()


# ── knowledge ─────────────────────────────────────────────────────────────────

def cmd_knowledge(args: argparse.Namespace) -> None:
    """Show knowledge base summary: lessons, failure patterns, freshness."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from . import knowledge as know_mod

    know_path = store.knowledge_path(workspace_path)
    mem_path = store.memory_path(workspace_path)
    h_path = store.history_path(workspace_path)
    from .context import load as ctx_load
    ctx_text = ctx_load(workspace_path)

    data = know_mod.load(know_path)
    stale = know_mod.is_stale(know_path, mem_path, h_path, ctx_text)
    lessons = data.get("lessons", [])
    patterns = data.get("patterns", [])
    failures = [p for p in patterns if p.get("type") == "failure_pattern"]
    successes = [p for p in patterns if p.get("type") == "success_pattern"]
    generated_at = data.get("generated_at", "")

    if getattr(args, "json", False):
        print(_json.dumps({
            "generated_at": generated_at,
            "stale": stale,
            "lesson_count": len(lessons),
            "failure_pattern_count": len(failures),
            "success_pattern_count": len(successes),
            "lessons": lessons,
            "failure_patterns": failures,
            "success_patterns": successes,
        }, indent=2))
        return

    SEP = "─" * 56

    def section(title: str) -> None:
        print(f"\n{title}")
        print(SEP)

    print(f"romyq knowledge: {root}")

    section("Knowledge Base")
    W = 24

    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    if generated_at:
        row("Generated:", generated_at[:19].replace("T", " ") + " UTC")
        row("Status:", "stale — run 'romyq run' to refresh" if stale else "fresh")
    else:
        row("Generated:", "(not yet generated — run 'romyq run')")
        row("Status:", "absent")
    row("Lessons:", str(len(lessons)))
    row("Failure patterns:", str(len(failures)))
    row("Success patterns:", str(len(successes)))

    section("Lessons")
    if lessons:
        for i, lesson in enumerate(lessons, 1):
            print(f"  {i}. {lesson}")
    else:
        print("  None. Run 'romyq run' to populate the knowledge base.")

    section("Failure Patterns")
    if failures:
        sorted_failures = sorted(failures, key=lambda p: p.get("count", 0), reverse=True)
        for p in sorted_failures[:10]:
            count = p.get("count", 0)
            preview = p.get("task_preview", "")[:65]
            fp = p.get("fingerprint", "")[:8]
            reason = p.get("last_reason", "")[:60]
            print(f"  [{count}x]  {preview}  (fp:{fp})")
            if reason:
                print(f"         last: {reason}")
    else:
        print("  None.")

    section("Success Patterns")
    if successes:
        sorted_successes = sorted(successes, key=lambda p: p.get("count", 0), reverse=True)
        for p in sorted_successes[:5]:
            count = p.get("count", 0)
            preview = p.get("task_preview", "")[:65]
            print(f"  [{count}x]  {preview}")
    else:
        print("  None.")

    print()


# ── patterns ──────────────────────────────────────────────────────────────────

def cmd_patterns(args: argparse.Namespace) -> None:
    """Show extracted failure and success patterns from the knowledge base."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from . import knowledge as know_mod

    know_path = store.knowledge_path(workspace_path)
    data = know_mod.load(know_path)
    patterns = data.get("patterns", [])
    failures = know_mod.top_failure_patterns(know_path)
    successes = know_mod.top_success_patterns(know_path)
    generated_at = data.get("generated_at", "")

    if getattr(args, "json", False):
        print(_json.dumps({
            "generated_at": generated_at,
            "total_patterns": len(patterns),
            "failure_patterns": failures,
            "success_patterns": successes,
        }, indent=2))
        return

    SEP = "─" * 56

    def section(title: str) -> None:
        print(f"\n{title}")
        print(SEP)

    print(f"romyq patterns: {root}")
    if generated_at:
        print(f"  (knowledge generated: {generated_at[:19].replace('T', ' ')} UTC)")

    section("Failure Patterns")
    if failures:
        for i, p in enumerate(failures, 1):
            count = p.get("count", 0)
            preview = p.get("task_preview", "")[:70]
            fp = p.get("fingerprint", "")
            reason = p.get("last_reason", "")[:80]
            print(f"  {i}. [{count}x]  {preview}")
            print(f"     fp: {fp}  last: {reason or '(unknown)'}")
    else:
        print("  No failure patterns recorded.")

    section("Success Patterns")
    if successes:
        for i, p in enumerate(successes, 1):
            count = p.get("count", 0)
            preview = p.get("task_preview", "")[:70]
            fp = p.get("fingerprint", "")
            print(f"  {i}. [{count}x]  {preview}")
            print(f"     fp: {fp}")
    else:
        print("  No success patterns recorded.")

    print()


# ── rules ─────────────────────────────────────────────────────────────────────

def cmd_rules(args: argparse.Namespace) -> None:
    """Manage project rules."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .rules import (
        add_rule, remove_rule, list_rules as list_active_rules,
        format_rules, rules_text,
    )
    from .steering import candidate_promotions
    from .events import emit as ev_emit
    from . import events as ev_mod

    r_path = store.rules_path(workspace_path)
    e_path = store.events_path(workspace_path)

    action = getattr(args, "action", "list") or "list"

    if action == "add":
        text = " ".join(getattr(args, "text_parts", []))
        if not text:
            print("Error: rule text cannot be empty.")
            print("Usage: romyq rules add \"Never use SQLite\"")
            sys.exit(1)
        rule_id = add_rule(r_path, text)
        ev_emit(e_path, ev_mod.RULE_ADDED, rule_id=rule_id, text=text[:100])
        try:
            from .decisions import record as record_decision
            record_decision(store.decisions_path(workspace_path), "rule_added", text)
        except Exception:
            pass
        print(f"Rule added [{rule_id}]: {text}")

    elif action == "remove":
        text = " ".join(getattr(args, "text_parts", []))
        if not text:
            print("Error: rule ID or text required.")
            print("Usage: romyq rules remove <id_or_text>")
            sys.exit(1)
        removed = remove_rule(r_path, text)
        if removed:
            ev_emit(e_path, ev_mod.RULE_REMOVED, text=text[:100])
            try:
                from .decisions import record as record_decision
                record_decision(store.decisions_path(workspace_path), "rule_removed", text)
            except Exception:
                pass
            print(f"Rule removed: {text}")
        else:
            print(f"No active rule found matching: {text}")
            sys.exit(1)

    else:
        # List active rules + promotion suggestions
        if getattr(args, "json", False):
            active = list_active_rules(r_path)
            suggestions = candidate_promotions(e_path)
            print(_json.dumps({
                "rules": active,
                "promotion_suggestions": suggestions,
            }, indent=2))
            return

        print(f"romyq rules: {root}\n")
        active = list_active_rules(r_path)
        if active:
            print(f"  {len(active)} active rule(s):\n")
            print(format_rules(r_path))
        else:
            print("  No rules defined.")
            print("  Add one with: romyq rules add \"Never use SQLite\"")

        suggestions = candidate_promotions(e_path)
        if suggestions:
            print(f"\n  Promotion suggestions (repeated operator instructions):")
            for s in suggestions[:5]:
                print(f"    → {s}")
            print("\n  Promote with: romyq rules add \"<suggestion>\"")
        print()


# ── decisions ─────────────────────────────────────────────────────────────────

def cmd_decisions(args: argparse.Namespace) -> None:
    """Show the governance decision log."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .decisions import recent as recent_decisions, count as decisions_count, count_by_type as dec_by_type

    d_path = store.decisions_path(workspace_path)
    limit = getattr(args, "last", 20)

    if getattr(args, "json", False):
        entries = recent_decisions(d_path, limit=limit)
        print(_json.dumps(entries, indent=2))
        return

    SEP = "─" * 56

    def section(title: str) -> None:
        print(f"\n{title}")
        print(SEP)

    print(f"romyq decisions: {root}")

    total = decisions_count(d_path)
    by_type = dec_by_type(d_path)

    section("Summary")
    print(f"  Total decisions: {total}")
    if by_type:
        for t, c in sorted(by_type.items(), key=lambda x: -x[1]):
            print(f"    {t}: {c}")

    section(f"Recent Decisions (last {limit})")
    entries = recent_decisions(d_path, limit=limit)
    if entries:
        for d in entries:
            ts = d.get("timestamp", "")[:19].replace("T", " ")
            type_ = d.get("type", "?")
            detail = d.get("detail", "")[:80]
            print(f"  [{ts}] {type_}: {detail}")
    else:
        print("  No decisions recorded yet.")
    print()


# ── readiness ────────────────────────────────────────────────────────────────

def cmd_readiness(args: argparse.Namespace) -> None:
    """Show mission readiness score across capability categories."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .readiness import compute_from_path, format_readiness
    ps_path = store.project_state_path(workspace_path)
    readiness = compute_from_path(ps_path)

    if getattr(args, "json", False):
        print(_json.dumps(readiness, indent=2))
        return

    print(f"romyq readiness: {root}\n")
    print(format_readiness(readiness))

    from .stop_conditions import evaluate, format_stop_conditions
    try:
        state = load_state(store.state_path(workspace_path))
    except Exception:
        state = {}
    result = evaluate(readiness, state)
    print()
    print(format_stop_conditions(result))


# ── capabilities ──────────────────────────────────────────────────────────────

def cmd_capabilities(args: argparse.Namespace) -> None:
    """Show or update the project capability model."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .capabilities import (
        list_capabilities, format_capabilities, set_capability,
        infer_from_history, capability_summary,
    )
    ps_path = store.project_state_path(workspace_path)

    action = getattr(args, "action", "list") or "list"

    if action == "set":
        name = getattr(args, "name", "") or ""
        status = getattr(args, "status", "") or ""
        if not name or not status:
            print("Usage: romyq capabilities set <name> <status>")
            print("  status: missing | partial | complete")
            sys.exit(1)
        try:
            set_capability(ps_path, name, status)
            print(f"Capability updated: {name} → {status}")
        except ValueError as e:
            print(f"Error: {e}")
            sys.exit(1)
        return

    if action == "infer":
        infer_from_history(ps_path, store.history_path(workspace_path))
        print("Capabilities inferred from task history.")

    if getattr(args, "json", False):
        print(_json.dumps(list_capabilities(ps_path), indent=2))
        return

    print(f"romyq capabilities: {root}\n")
    caps = list_capabilities(ps_path)
    if caps:
        print(format_capabilities(ps_path))
        print()
        s = capability_summary(ps_path)
        print(f"  Total: {s['total']}  Complete: {s['complete']}  "
              f"Partial: {s['partial']}  Missing: {s['missing']}")
    else:
        print("  No capabilities tracked yet.")
        print("  They are inferred automatically as tasks complete.")
        print("  Or set one manually: romyq capabilities set Authentication complete")


# ── constitution ──────────────────────────────────────────────────────────────

def cmd_constitution(args: argparse.Namespace) -> None:
    """Generate or display the project constitution (.romyq/project.md)."""
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .constitution import write, generate
    ps_path = store.project_state_path(workspace_path)

    if getattr(args, "print_only", False):
        content = generate(
            str(root),
            rules_path=store.rules_path(workspace_path),
            knowledge_path=store.knowledge_path(workspace_path),
            project_state_path=ps_path,
            events_path=store.events_path(workspace_path),
        )
        print(content)
        return

    path = write(
        str(root),
        rules_path=store.rules_path(workspace_path),
        knowledge_path=store.knowledge_path(workspace_path),
        project_state_path=ps_path,
        events_path=store.events_path(workspace_path),
    )
    print(f"Project constitution written to {path}")
    try:
        from .events import emit as _emit
        from . import events as _ev
        _emit(store.events_path(workspace_path), _ev.CONSTITUTION_GENERATED, path=path)
    except Exception:
        pass


# ── project-timeline ──────────────────────────────────────────────────────────

def cmd_project_timeline(args: argparse.Namespace) -> None:
    """Show the project evolution timeline (capability-level, not tasks)."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .timeline import build_timeline, format_timeline
    h_path = store.history_path(workspace_path)
    limit = getattr(args, "last", 20)

    if getattr(args, "json", False):
        events = build_timeline(h_path, limit=limit)
        print(_json.dumps(events, indent=2))
        return

    print(f"romyq project-timeline: {root}\n")
    print(format_timeline(h_path, limit=limit))


# ── learn ─────────────────────────────────────────────────────────────────────

def cmd_learn(args: argparse.Namespace) -> None:
    """Generate or refresh .romyq/context.md from static analysis."""
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.ensure_dir(workspace_path)

    from .context import write as ctx_write
    path = ctx_write(workspace_path)
    print(f"Repository context written to {path}")
    print()
    from .context import load as ctx_load
    print(ctx_load(workspace_path))


# ── stats ─────────────────────────────────────────────────────────────────────

def cmd_stats(args: argparse.Namespace) -> None:
    """Show long-run operational statistics."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    try:
        state = load_state(store.state_path(workspace_path))
    except Exception:
        print("No state found. Has romyq been run yet?")
        sys.exit(1)

    from .metrics import compute as compute_metrics
    m = compute_metrics(
        state=state,
        history_path=store.history_path(workspace_path),
        events_path=store.events_path(workspace_path),
        memory_path=store.memory_path(workspace_path),
        decisions_path=store.decisions_path(workspace_path),
    )

    if getattr(args, "json", False):
        print(_json.dumps(m._asdict(), indent=2))
        return

    W = 26

    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    print(f"romyq stats: {root}\n")
    row("Tasks completed:", str(m.tasks_completed))
    row("Tasks blocked:", str(m.tasks_blocked))
    row("History entries:", str(m.history_entries))
    row("Validator pass / fail:", f"{m.success_count} / {m.failure_count}")
    if m.validator_pass_rate >= 0:
        row("Validator pass rate:", f"{m.validator_pass_rate * 100:.1f}%")
    else:
        row("Validator pass rate:", "n/a (no history)")
    row("Cancellations:", str(m.cancellation_count))
    row("Rate-limit events:", str(m.rate_limit_count))
    row("Total events logged:", str(m.event_count))
    row("Runtime (hours):", f"{m.runtime_hours:.2f}")
    if m.first_event_ts:
        row("First event:", m.first_event_ts[:19].replace("T", " ") + " UTC")
    if m.last_event_ts:
        row("Last event:", m.last_event_ts[:19].replace("T", " ") + " UTC")
    if m.task_retry_rate > 0 or m.avg_attempts_per_task > 0:
        print()
        print("  Memory-derived:")
        row("Task retry rate:", f"{m.task_retry_rate * 100:.1f}%")
        row("Avg attempts/task:", f"{m.avg_attempts_per_task:.2f}")
        row("Blocked-task rate:", f"{m.blocked_task_rate * 100:.1f}%")
        row("Planner loops:", str(m.planner_loop_count))

    print()
    print("  Governance:")
    row("Rules triggered:", str(m.rules_triggered))
    row("Guardrails triggered:", str(m.guardrails_triggered))
    row("Decisions recorded:", str(m.decisions_recorded))
    row("Plan repairs:", str(m.plan_repairs))


# ── timeline ──────────────────────────────────────────────────────────────────

def cmd_timeline(args: argparse.Namespace) -> None:
    """Show a human-readable event timeline."""
    import json as _json
    workspace_path = _resolve_workspace(args)

    if not Path(workspace_path).is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .events import tail
    events = tail(store.events_path(workspace_path), n=args.last)

    if not events:
        print("No events recorded yet.")
        return

    if getattr(args, "json", False):
        print(_json.dumps(events, indent=2))
        return

    _EVT_LABELS = {
        "loop_started":        "▶  Loop started",
        "loop_stopped":        "■  Loop stopped",
        "task_started":        "→  Task started",
        "task_completed":      "✓  Task completed",
        "task_blocked":        "✗  Task blocked",
        "validator_passed":    "✓  Validator passed",
        "validator_failed":    "✗  Validator failed",
        "no_action_required":  "–  No action required",
        "retry":               "↺  Retry",
        "pause_detected":      "‖  Paused",
        "resume_detected":     "▶  Resumed",
        "stop_detected":       "■  Stop detected",
        "rate_limit_detected": "⏳ Rate limit",
        "rate_limit_recovered":"✓  Rate limit cleared",
        "claude_cancelled":    "✗  Claude cancelled",
        "phase_changed":       "⟳  Phase changed",
        "crash_recovered":     "↺  Crash recovered",
    }

    for entry in events:
        ts = entry.get("ts", "")[:19].replace("T", " ")
        evt = entry.get("event", "?")
        label = _EVT_LABELS.get(evt, f"   {evt}")
        extras = {k: v for k, v in entry.items() if k not in ("ts", "event")}
        detail = ""
        if "reason" in extras:
            detail = f"  {extras['reason']}"
        elif "task_preview" in extras:
            detail = f"  {str(extras['task_preview'])[:60]}"
        elif "key" in extras:
            detail = f"  key={extras['key']}"
        print(f"[{ts}] {label}{detail}")


# ── roadmap ───────────────────────────────────────────────────────────────────

def cmd_roadmap(args: argparse.Namespace) -> None:
    """Show the lifecycle roadmap with phase progress."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .lifecycle import load as lc_load, format_roadmap, progress_summary
    lc_path = store.lifecycle_path(workspace_path)
    data = lc_load(lc_path)

    if getattr(args, "json", False):
        print(_json.dumps(data, indent=2))
        return

    if not data.get("phases"):
        print("No lifecycle found.")
        print("A lifecycle is generated automatically when 'romyq run' starts.")
        return

    print(f"romyq roadmap: {root}\n")

    from .profile import load as prof_load, format_profile
    prof_path = store.profile_path(workspace_path)
    print(format_profile(prof_path))
    print()

    try:
        from .readiness import compute_from_path, format_readiness
        ps_path = store.project_state_path(workspace_path)
        rdns = compute_from_path(ps_path)
        print(f"Readiness     : {rdns['overall']:.0f}%  ({rdns.get('label', '')})")
    except Exception:
        pass

    print()
    print(format_roadmap(data))
    print()

    crit = data.get("done_criteria", [])
    if crit:
        print(f"Done criteria : {', '.join(crit)}")


# ── lifecycle ─────────────────────────────────────────────────────────────────

def cmd_lifecycle(args: argparse.Namespace) -> None:
    """Show or manage the software lifecycle."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .lifecycle import (
        load as lc_load, format_roadmap, format_current_phase,
        progress_summary, all_phases_complete,
    )
    lc_path = store.lifecycle_path(workspace_path)
    data = lc_load(lc_path)

    action = getattr(args, "action", "show") or "show"

    if action == "reset":
        Path(lc_path).unlink(missing_ok=True)
        print("Lifecycle reset. It will be regenerated on the next 'romyq run'.")
        return

    if getattr(args, "json", False):
        print(_json.dumps(data, indent=2))
        return

    if not data.get("phases"):
        print("No lifecycle found.")
        print("Run 'romyq run' to generate one, or set complexity with 'romyq profile'.")
        return

    SEP = "─" * 56

    def section(title: str) -> None:
        print(f"\n{title}")
        print(SEP)

    print(f"romyq lifecycle: {root}")

    section("Lifecycle Overview")
    print(format_roadmap(data))

    section("Current Phase")
    print(format_current_phase(data))

    section("Done Criteria")
    crit = data.get("done_criteria", [])
    if crit:
        for c in crit:
            print(f"  □ {c}")
    else:
        print("  (none defined)")

    section("Summary")
    summ = progress_summary(data)
    W = 22

    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    row("Overall progress:", f"{summ['overall_percentage']}%")
    row("Phases complete:", f"{summ['complete_phases']}/{summ['total_phases']}")
    row("Tasks complete:", f"{summ['completed_tasks']}/{summ['total_tasks']}")
    row("Tasks remaining:", str(summ["remaining_tasks"]))
    if all_phases_complete(data):
        print("\n  All phases complete!")

    print()


# ── phase ─────────────────────────────────────────────────────────────────────

def cmd_phase(args: argparse.Namespace) -> None:
    """Show the current lifecycle phase and its tasks."""
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .lifecycle import load as lc_load, format_current_phase, current_phase
    lc_path = store.lifecycle_path(workspace_path)
    data = lc_load(lc_path)

    if not data.get("phases"):
        print("No lifecycle found. Run 'romyq run' to generate one.")
        return

    print(f"romyq phase: {root}\n")
    print(format_current_phase(data))

    phase = current_phase(data)
    if phase:
        pct = phase.get("percentage_complete", 0)
        total = phase.get("total_tasks", 0)
        done = phase.get("completed_tasks", 0)
        print(f"\n  Progress: {done}/{total} tasks  ({pct}%)")


# ── profile ───────────────────────────────────────────────────────────────────

def cmd_profile(args: argparse.Namespace) -> None:
    """Show or set the project complexity profile."""
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.ensure_dir(workspace_path)

    from .profile import set_complexity, format_profile, VALID_LEVELS
    prof_path = store.profile_path(workspace_path)

    level = getattr(args, "level", None)
    if level:
        if level not in VALID_LEVELS:
            print(f"Error: complexity must be one of {sorted(VALID_LEVELS)}")
            sys.exit(1)
        set_complexity(prof_path, level)
        print(f"Complexity set to: {level}")
        print("Tip: delete .romyq/lifecycle.json to regenerate with the new profile.")
        return

    print(f"romyq profile: {root}\n")
    print(format_profile(prof_path))


# ── recommendation ────────────────────────────────────────────────────────────

def cmd_recommendation(args: argparse.Namespace) -> None:
    """Show the current project recommendation (Continue/Pause/Review/Stop)."""
    import json as _json
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .recommendation import recommend_from_paths, format_recommendation
    result = recommend_from_paths(workspace_path=workspace_path)

    if getattr(args, "json", False):
        print(_json.dumps(result, indent=2))
        return

    print(f"romyq recommendation: {root}\n")
    print(format_recommendation(result))


# ── dashboard ────────────────────────────────────────────────────────────────

def cmd_dashboard(args: argparse.Namespace) -> None:
    """Show the lifecycle-first project dashboard."""
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .dashboard import render
    render(workspace_path)


# ── architecture ──────────────────────────────────────────────────────────────

def cmd_architecture(args: argparse.Namespace) -> None:
    """Show the lifecycle architecture flow diagram."""
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    store.migrate(workspace_path)

    from .lifecycle import load as lc_load
    from .viz import format_architecture_flow
    lc_path = store.lifecycle_path(workspace_path)
    data = lc_load(lc_path)

    if not data.get("phases"):
        print("No lifecycle found.")
        print("Run 'romyq run' to generate one, or set complexity with 'romyq profile'.")
        return

    print(f"romyq architecture: {root}\n")
    print(format_architecture_flow(data))

    crit = data.get("done_criteria", [])
    if crit:
        print()
        print("  Done criteria:")
        for c in crit:
            print(f"    □ {c}")
    print()


# ── shell ─────────────────────────────────────────────────────────────────────

def cmd_shell(args: argparse.Namespace) -> None:
    """Launch the live operator shell alongside a running romyq loop."""
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    if not root.is_dir():
        print(f"Workspace not found: {workspace_path}")
        sys.exit(1)

    from .shell import run_shell
    run_shell(str(root))


# ── version ───────────────────────────────────────────────────────────────────

def cmd_version(args: argparse.Namespace) -> None:
    import json
    import os
    import sys
    from importlib.metadata import PackageNotFoundError, distribution

    W = 12  # label column width

    def row(label: str, value: str) -> None:
        print(f"  {label:<{W}}{value}")

    print(f"romyq {__version__}")

    try:
        dist = distribution("romyq")
        direct_url_text = dist.read_text("direct_url.json")
        if direct_url_text:
            data = json.loads(direct_url_text)
            if data.get("dir_info", {}).get("editable"):
                src = data.get("url", "").removeprefix("file://")
                row("install", f"editable ({src})")
                row("note", "run 'pip install -e .' after bumping pyproject.toml version")
            else:
                row("install", "wheel or sdist")
        else:
            # Old-style egg-info editable (no direct_url.json)
            dist_path = str(getattr(dist, "_path", ""))
            if "egg-info" in dist_path or "egg-link" in dist_path:
                row("install", "editable (legacy egg-info — re-run 'pip install -e .' after version bumps)")
            else:
                row("install", "wheel or sdist")
    except PackageNotFoundError:
        row("install", "none — package not installed via pip (version above is a fallback)")

    if __version__ == "0.0.0+unknown":
        row("warning", "version unknown — install with 'pip install -e .' or 'pip install romyq'")

    row("python", sys.version.split()[0])

    # Executable path — shows which binary is actually running.
    # Critical for catching PATH-shadowing by a global install.
    exe = os.path.realpath(sys.argv[0])
    row("executable", exe)

    # Venv detection: VIRTUAL_ENV env var (set by venv/virtualenv on activation)
    # falls back to comparing sys.prefix with sys.base_prefix.
    virtual_env = os.environ.get("VIRTUAL_ENV", "")
    if virtual_env:
        row("venv", virtual_env)
    elif hasattr(sys, "real_prefix") or sys.prefix != sys.base_prefix:
        row("venv", sys.prefix)
    else:
        row("venv", "none")
        print()
        print("  Warning: not running inside a virtual environment.")
        print("           If you are testing a wheel install, activate the venv first.")
        print("           Quick check: python -m pip show romyq")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="romyq",
        description="Autonomous AI software project manager.",
    )
    parser.add_argument("--version", action="version", version=f"romyq {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p_init = sub.add_parser("init", help="Launch the interactive setup wizard")
    p_init.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace directory (default: current directory)",
    )
    p_init.add_argument(
        "--no-vcs",
        action="store_true",
        default=False,
        help="Skip git initialization",
    )
    p_init.add_argument(
        "--no-wizard",
        action="store_true",
        default=False,
        help="Use legacy non-interactive init (no wizard)",
    )
    p_init.set_defaults(func=cmd_init)

    p_attach = sub.add_parser("attach", help="Attach Romyq to an existing repository")
    p_attach.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the repository (default: current directory)",
    )
    p_attach.set_defaults(func=cmd_attach)

    p_note = sub.add_parser("note", help="Add a steering note for the AI manager")
    p_note.add_argument("message", help="The note to add (e.g. 'Focus on admin UX.')")
    p_note.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory)",
    )
    p_note.set_defaults(func=cmd_note)

    p_info = sub.add_parser("info", help="Show what Romyq detects about a repository")
    p_info.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the repository (default: current directory)",
    )
    p_info.set_defaults(func=cmd_info)

    p_run = sub.add_parser("run", help="Start the autonomous development loop")
    p_run.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_run.add_argument(
        "--until-complete",
        action="store_true",
        default=False,
        help="Stop when the mission is complete (default: run indefinitely)",
    )
    p_run.add_argument(
        "--approval",
        action="store_true",
        default=False,
        help="Require operator approval before each task is executed",
    )
    p_run.set_defaults(func=cmd_run)

    p_steer = sub.add_parser("steer", help="Record an operator instruction for the active loop")
    p_steer.add_argument("instruction", help="Instruction to send to the planner")
    p_steer.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_steer.set_defaults(func=cmd_steer)

    p_status = sub.add_parser("status", help="Show current run status")
    p_status.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_status.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output state as JSON",
    )
    p_status.set_defaults(func=cmd_status)

    p_logs = sub.add_parser("logs", help="Show recent task history")
    p_logs.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_logs.add_argument(
        "--last", type=int, default=10, metavar="N",
        help="Number of entries to show (default: 10)",
    )
    p_logs.set_defaults(func=cmd_logs)

    p_doctor = sub.add_parser("doctor", help="Check environment and configuration")
    p_doctor.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_doctor.set_defaults(func=cmd_doctor)

    p_health = sub.add_parser("health", help="Show high-level project health summary")
    p_health.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_health.set_defaults(func=cmd_health)

    p_report = sub.add_parser("report", help="Show a full human-readable project report")
    p_report.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_report.set_defaults(func=cmd_report)

    p_ui = sub.add_parser("ui", help="Launch the Textual TUI dashboard")
    p_ui.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_ui.set_defaults(func=cmd_ui)

    p_version = sub.add_parser("version", help="Show version and install information")
    p_version.set_defaults(func=cmd_version)

    p_events = sub.add_parser("events", help="Show recent event log entries")
    p_events.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_events.add_argument(
        "--last", type=int, default=30, metavar="N",
        help="Number of entries to show (default: 30)",
    )
    p_events.set_defaults(func=cmd_events)

    p_explain = sub.add_parser("explain", help="Show full diagnostic state, task, failures, and evidence")
    p_explain.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_explain.set_defaults(func=cmd_explain)

    p_planning = sub.add_parser("planning", help="Show planning context, loop detection, and memory diagnostics")
    p_planning.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_planning.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output diagnostics as JSON",
    )
    p_planning.set_defaults(func=cmd_planning)

    p_memory = sub.add_parser("memory", help="Show execution memory analysis")
    p_memory.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_memory.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output memory analysis as JSON",
    )
    p_memory.set_defaults(func=cmd_memory)

    p_plan = sub.add_parser("plan", help="Show the mission decomposition plan")
    p_plan.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_plan.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output plan as JSON",
    )
    p_plan.set_defaults(func=cmd_plan)

    p_knowledge = sub.add_parser("knowledge", help="Show knowledge base: lessons, patterns, freshness")
    p_knowledge.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_knowledge.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output knowledge as JSON",
    )
    p_knowledge.set_defaults(func=cmd_knowledge)

    p_patterns = sub.add_parser("patterns", help="Show extracted failure and success patterns")
    p_patterns.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_patterns.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output patterns as JSON",
    )
    p_patterns.set_defaults(func=cmd_patterns)

    p_rules = sub.add_parser("rules", help="Manage project governance rules")
    p_rules.add_argument(
        "action",
        nargs="?",
        choices=["add", "remove", "list"],
        default="list",
        help="Action: add, remove, or list (default: list)",
    )
    p_rules.add_argument(
        "text_parts",
        nargs="*",
        help="Rule text (for add/remove)",
    )
    p_rules.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_rules.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON",
    )
    p_rules.set_defaults(func=cmd_rules)

    p_decisions = sub.add_parser("decisions", help="Show the governance decision log")
    p_decisions.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_decisions.add_argument(
        "--last", type=int, default=20, metavar="N",
        help="Number of decisions to show (default: 20)",
    )
    p_decisions.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output as JSON",
    )
    p_decisions.set_defaults(func=cmd_decisions)

    p_learn = sub.add_parser("learn", help="Generate or refresh .romyq/context.md from static analysis")
    p_learn.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_learn.set_defaults(func=cmd_learn)

    p_stats = sub.add_parser("stats", help="Show long-run operational statistics")
    p_stats.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_stats.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output stats as JSON",
    )
    p_stats.set_defaults(func=cmd_stats)

    p_timeline = sub.add_parser("timeline", help="Show a human-readable event timeline")
    p_timeline.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_timeline.add_argument(
        "--last", type=int, default=50, metavar="N",
        help="Number of events to show (default: 50)",
    )
    p_timeline.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output events as JSON",
    )
    p_timeline.set_defaults(func=cmd_timeline)

    p_readiness = sub.add_parser("readiness", help="Show mission readiness score across categories")
    p_readiness.add_argument("workspace", nargs="?", default=None)
    p_readiness.add_argument("--json", action="store_true", default=False)
    p_readiness.set_defaults(func=cmd_readiness)

    p_caps = sub.add_parser("capabilities", help="Show or update the project capability model")
    p_caps.add_argument("action", nargs="?", choices=["list", "set", "infer"], default="list")
    p_caps.add_argument("name", nargs="?", default=None, help="Capability name (for 'set')")
    p_caps.add_argument("status", nargs="?", default=None, help="Status: missing|partial|complete")
    p_caps.add_argument("workspace", nargs="?", default=None)
    p_caps.add_argument("--json", action="store_true", default=False)
    p_caps.set_defaults(func=cmd_capabilities)

    p_constitution = sub.add_parser("constitution", help="Generate project constitution (.romyq/project.md)")
    p_constitution.add_argument("workspace", nargs="?", default=None)
    p_constitution.add_argument("--print", dest="print_only", action="store_true", default=False,
                                help="Print to stdout instead of writing to disk")
    p_constitution.set_defaults(func=cmd_constitution)

    p_ptimeline = sub.add_parser("project-timeline", help="Show project evolution timeline")
    p_ptimeline.add_argument("workspace", nargs="?", default=None)
    p_ptimeline.add_argument("--last", type=int, default=20, metavar="N")
    p_ptimeline.add_argument("--json", action="store_true", default=False)
    p_ptimeline.set_defaults(func=cmd_project_timeline)

    p_roadmap = sub.add_parser("roadmap", help="Show the lifecycle roadmap with phase progress")
    p_roadmap.add_argument("workspace", nargs="?", default=None)
    p_roadmap.add_argument("--json", action="store_true", default=False)
    p_roadmap.set_defaults(func=cmd_roadmap)

    p_lifecycle = sub.add_parser("lifecycle", help="Show or manage the software lifecycle")
    p_lifecycle.add_argument("action", nargs="?", choices=["show", "reset"], default="show")
    p_lifecycle.add_argument("workspace", nargs="?", default=None)
    p_lifecycle.add_argument("--json", action="store_true", default=False)
    p_lifecycle.set_defaults(func=cmd_lifecycle)

    p_phase = sub.add_parser("phase", help="Show the current lifecycle phase and tasks")
    p_phase.add_argument("workspace", nargs="?", default=None)
    p_phase.set_defaults(func=cmd_phase)

    p_profile = sub.add_parser("profile", help="Show or set the project complexity profile")
    p_profile.add_argument("level", nargs="?", default=None,
                           help="Complexity level: basic | intermediate | advanced")
    p_profile.add_argument("workspace", nargs="?", default=None)
    p_profile.set_defaults(func=cmd_profile)

    p_recommendation = sub.add_parser("recommendation",
                                       help="Show the current project recommendation")
    p_recommendation.add_argument("workspace", nargs="?", default=None)
    p_recommendation.add_argument("--json", action="store_true", default=False)
    p_recommendation.set_defaults(func=cmd_recommendation)

    p_dashboard = sub.add_parser("dashboard", help="Show the lifecycle-first project dashboard")
    p_dashboard.add_argument("workspace", nargs="?", default=None)
    p_dashboard.set_defaults(func=cmd_dashboard)

    p_architecture = sub.add_parser("architecture", help="Show the lifecycle architecture flow diagram")
    p_architecture.add_argument("workspace", nargs="?", default=None)
    p_architecture.set_defaults(func=cmd_architecture)

    p_shell = sub.add_parser("shell", help="Launch the live operator shell alongside a running loop")
    p_shell.add_argument("workspace", nargs="?", default=None)
    p_shell.set_defaults(func=cmd_shell)

    p_pause = sub.add_parser("pause", help="Pause the loop after the current task")
    p_pause.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_pause.set_defaults(func=cmd_pause)

    p_resume = sub.add_parser("resume", help="Resume a paused loop")
    p_resume.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_resume.set_defaults(func=cmd_resume)

    p_stop = sub.add_parser("stop", help="Request graceful shutdown after the current task")
    p_stop.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
    )
    p_stop.set_defaults(func=cmd_stop)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
