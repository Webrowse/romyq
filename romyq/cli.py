import argparse
import os
import shutil
import sys
from pathlib import Path

from . import __version__, notes as notes_mod, store
from .findings import unresolved as findings_unresolved
from .mission import create_template, exists as mission_exists, load as load_mission
from .workspace import bootstrap, is_git_repo, _ensure_gitignore_entry, detect, git_log
from .state import load as load_state
from .history import recent


def _resolve_workspace(args: argparse.Namespace, default: str = ".") -> str:
    return getattr(args, "workspace", None) or os.getenv("ROMYQ_WORKSPACE", default)


# ── init ──────────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> None:
    workspace_path = _resolve_workspace(args)
    root = Path(workspace_path).resolve()

    bootstrap(workspace_path)           # creates git repo + .gitignore + initial commit
    store.ensure_dir(workspace_path)    # creates .romyq/

    created = create_template(str(root))   # mission.md inside workspace, not CWD parent
    if created:
        print("Created mission.md — edit it to describe what you want to build.")
    else:
        print("mission.md already exists.")

    print(f"\nWorkspace ready at: {root}/")
    print(f"State directory:    {root}/.romyq/")
    print("\nNext steps:")
    print("  1. Edit mission.md")
    print("  2. Set DEEPSEEK_API_KEY in .env or your environment")
    if workspace_path == ".":
        print("  3. Run: romyq run")
    else:
        print(f"  3. cd {root} && romyq run")


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
    run(workspace_path, until_complete=args.until_complete)


# ── status ────────────────────────────────────────────────────────────────────

def cmd_status(args: argparse.Namespace) -> None:
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

    print(f"Workspace:       {Path(workspace_path).resolve()}")
    print(f"Status:          {state['status']}")
    print(f"Tasks completed: {state['tasks_completed']}")
    print(f"Last commit:     {state['last_commit'] or '(none)'}")
    print(f"Heartbeat:       {state['heartbeat'] or '(none)'}")
    print(f"Audit interval:  every {state['audit_interval']} tasks")

    if state["current_task"]:
        task_preview = state["current_task"][:120].replace("\n", " ")
        print(f"Current task:    {task_preview}...")


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


# ── version ───────────────────────────────────────────────────────────────────

def cmd_version(args: argparse.Namespace) -> None:
    import json
    import sys
    from importlib.metadata import PackageNotFoundError, distribution

    print(f"romyq {__version__}")

    try:
        dist = distribution("romyq")
        direct_url_text = dist.read_text("direct_url.json")
        if direct_url_text:
            data = json.loads(direct_url_text)
            if data.get("dir_info", {}).get("editable"):
                src = data.get("url", "").removeprefix("file://")
                print(f"  install  editable ({src})")
                print("  note     run 'pip install -e .' after bumping pyproject.toml version")
            else:
                print("  install  wheel or sdist")
        else:
            # Old-style egg-info editable (no direct_url.json)
            dist_path = str(getattr(dist, "_path", ""))
            if "egg-info" in dist_path or "egg-link" in dist_path:
                print("  install  editable (legacy egg-info — re-run 'pip install -e .' after version bumps)")
            else:
                print("  install  wheel or sdist")
    except PackageNotFoundError:
        print("  install  none — package not installed via pip (version above is a fallback)")

    if __version__ == "0.0.0+unknown":
        print("  warning  version unknown — install with 'pip install -e .' or 'pip install romyq'")

    print(f"  python   {sys.version.split()[0]}")


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="romyq",
        description="Autonomous AI software project manager.",
    )
    parser.add_argument("--version", action="version", version=f"romyq {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p_init = sub.add_parser("init", help="Initialize a new romyq workspace")
    p_init.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace directory (default: current directory)",
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
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="Show current run status")
    p_status.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace (default: current directory or $ROMYQ_WORKSPACE)",
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
