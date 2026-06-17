import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import __version__
from .mission import create_template, exists as mission_exists
from .workspace import bootstrap, is_git_repo
from .state import load as load_state, STATE_FILE
from .history import recent, HISTORY_FILE


def cmd_init(args: argparse.Namespace) -> None:
    workspace_path = args.workspace

    created = create_template()
    if created:
        print("Created mission.md — edit it to describe what you want to build.")
    else:
        print("mission.md already exists.")

    bootstrap(workspace_path)
    print(f"\nWorkspace ready at: {workspace_path}/")
    print("\nNext steps:")
    print("  1. Edit mission.md")
    print("  2. Set DEEPSEEK_API_KEY in .env or your environment")
    print("  3. Run: romiq run")


def cmd_run(args: argparse.Namespace) -> None:
    from dotenv import load_dotenv
    load_dotenv()

    workspace_path = args.workspace or os.getenv("ROMIQ_WORKSPACE", "workspace")

    if not mission_exists():
        print("Error: mission.md not found. Run 'romiq init' first.")
        sys.exit(1)

    from .loop import run
    run(workspace_path)


def cmd_status(args: argparse.Namespace) -> None:
    try:
        state = load_state(STATE_FILE)
    except Exception:
        print("No state found. Has romiq been run yet?")
        sys.exit(1)

    print(f"Status:          {state['status']}")
    print(f"Tasks completed: {state['tasks_completed']}")
    print(f"Last commit:     {state['last_commit'] or '(none)'}")
    print(f"Heartbeat:       {state['heartbeat'] or '(none)'}")
    print(f"Audit interval:  every {state['audit_interval']} tasks")

    if state["current_task"]:
        task_preview = state["current_task"][:120].replace("\n", " ")
        print(f"Current task:    {task_preview}...")


def cmd_logs(args: argparse.Namespace) -> None:
    entries = recent(limit=args.last, path=HISTORY_FILE)

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

    print("romiq doctor\n")

    api_key = os.getenv("DEEPSEEK_API_KEY", "")
    check("DEEPSEEK_API_KEY", bool(api_key), "set" if api_key else "missing — add to .env")

    claude_bin = shutil.which("claude")
    check("claude CLI", bool(claude_bin), claude_bin or "not found in PATH")

    check("mission.md", mission_exists(), "found" if mission_exists() else "missing — run 'romiq init'")

    workspace_path = os.getenv("ROMIQ_WORKSPACE", "workspace")
    workspace_exists = Path(workspace_path).exists()
    check(f"workspace ({workspace_path}/)", workspace_exists, "exists" if workspace_exists else "missing — run 'romiq init'")

    if workspace_exists:
        git_ok = is_git_repo(workspace_path)
        check("workspace is a git repo", git_ok, "yes" if git_ok else "run 'romiq init'")

    print()
    if ok:
        print("All checks passed. Ready to run: romiq run")
    else:
        print("Some checks failed. Fix the issues above before running.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="romiq",
        description="Autonomous AI software project manager.",
    )
    parser.add_argument("--version", action="version", version=f"romiq {__version__}")

    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p_init = sub.add_parser("init", help="Initialize a new romiq project")
    p_init.add_argument(
        "workspace",
        nargs="?",
        default="workspace",
        help="Path to the workspace directory (default: workspace/)",
    )
    p_init.set_defaults(func=cmd_init)

    p_run = sub.add_parser("run", help="Start the autonomous development loop")
    p_run.add_argument(
        "workspace",
        nargs="?",
        default=None,
        help="Path to the workspace directory (default: $ROMIQ_WORKSPACE or workspace/)",
    )
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="Show current run status")
    p_status.set_defaults(func=cmd_status)

    p_logs = sub.add_parser("logs", help="Show recent task history")
    p_logs.add_argument("--last", type=int, default=10, metavar="N", help="Number of entries to show (default: 10)")
    p_logs.set_defaults(func=cmd_logs)

    p_doctor = sub.add_parser("doctor", help="Check environment and configuration")
    p_doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
