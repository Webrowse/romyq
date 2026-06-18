import argparse
import os
import shutil
import sys
from pathlib import Path

from . import __version__, notes as notes_mod, store
from .mission import create_template, exists as mission_exists
from .workspace import bootstrap, is_git_repo, _ensure_gitignore_entry, detect
from .state import load as load_state
from .history import recent


def _resolve_workspace(args: argparse.Namespace, default: str = ".") -> str:
    return getattr(args, "workspace", None) or os.getenv("ROMYQ_WORKSPACE", default)


# ── init ──────────────────────────────────────────────────────────────────────

def cmd_init(args: argparse.Namespace) -> None:
    workspace_path = args.workspace

    created = create_template()
    if created:
        print("Created mission.md — edit it to describe what you want to build.")
    else:
        print("mission.md already exists.")

    bootstrap(workspace_path)
    print(f"\nWorkspace ready at: {workspace_path}/")
    print(f"State directory:    {workspace_path}/.romyq/")
    print("\nNext steps:")
    print("  1. Edit mission.md")
    print("  2. Set DEEPSEEK_API_KEY in .env or your environment")
    print(f"  3. Run: romyq run {workspace_path}")


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

    # Create mission.md in CWD if absent
    mission_path = Path("mission.md").resolve()
    created = create_template()
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

    print("\nNext steps:")
    print("  1. Edit mission.md — describe your goals for this project")
    print(f"  2. romyq info {workspace_path}")
    print(f"  3. romyq run {workspace_path}")


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
        default="workspace",
        help="Path to the workspace directory (default: workspace/)",
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

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
