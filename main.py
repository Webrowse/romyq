import os
import sys
import time
from dotenv import load_dotenv

from manager import generate_task
from inspector import inspect_repository
from validator import validate_task
from task_history import add_entry
from mission import load_mission

from state import (
    load_state,
    save_state,
    heartbeat,
    set_current_task,
    increment_tasks,
    set_last_commit,
    next_mode,
    mark_audit_complete,
    mark_completed,
)

from claude_runner import (
    run_claude_with_retry,
)

from bootstrap import bootstrap_workspace
from audit_extractor import extract_and_save_findings
from completion_evaluator import evaluate_completion


load_dotenv()

STATE_FILE = "state.json"
STATE_MD = "state.md"


def parse_args() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]

    return os.getenv("ROMIQ_WORKSPACE", "workspace")


def read_file(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def write_state_md(
    task: str,
    result_stdout: str,
    result_stderr: str,
    repo: dict,
    validation_ok: bool,
    validation_reason: str,
) -> None:
    content = f"""
# Current State

## Last Task

{task}

## Last Commit

{repo["latest_commit"]}

## Validation

Success: {validation_ok}

Reason:

{validation_reason}

## Git Status

{repo["git_status"]}

## Repository Changes

{repo["diff_stat"]}

## Claude Output

{result_stdout}

## Claude Errors

{result_stderr}
"""

    with open(STATE_MD, "w") as f:
        f.write(content)


def main() -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY")

    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY missing")

    workspace = parse_args()

    bootstrap_workspace(workspace)

    while True:
        state = load_state(STATE_FILE)

        heartbeat(state)

        mission = load_mission()

        state_text = read_file(STATE_MD)

        repo_before = inspect_repository(workspace)

        if state["tasks_completed"] > 0:
            completed, reason = evaluate_completion(
                api_key=api_key,
                mission=mission,
                workspace=workspace,
                git_log=repo_before["git_log"],
            )

            print("\n" + "=" * 80)
            print("COMPLETION CHECK")
            print("=" * 80)
            print(f"completed: {completed}")
            print(f"reason: {reason}")
            print("=" * 80)

            if completed:
                mark_completed(state)
                heartbeat(state)
                save_state(state, STATE_FILE)
                print("\nMISSION COMPLETE")
                print(reason)
                break

        mode = next_mode(state)

        task = generate_task(
            api_key=api_key,
            mission=mission,
            state=state_text,
            tasks_completed=state["tasks_completed"],
            git_log=repo_before["git_log"],
            git_status=repo_before["git_status"],
            mode=mode,
            workspace=workspace,
        )

        print("\n" + "=" * 80)
        print("MODE:", mode)
        print("=" * 80)
        print(task)
        print("=" * 80)

        set_current_task(state, task)

        save_state(state, STATE_FILE)

        before_commit = repo_before["latest_commit"]

        result = run_claude_with_retry(
            workspace=workspace,
            task=task,
        )

        repo_after = inspect_repository(workspace)

        after_commit = repo_after["latest_commit"]

        (
            validation_ok,
            validation_reason,
        ) = validate_task(
            workspace=workspace,
            before_commit=before_commit,
            after_commit=after_commit,
            claude_returncode=result.returncode,
        )

        add_entry(
            task=task,
            mode=mode,
            success=validation_ok,
            commit=after_commit,
            validation_reason=validation_reason,
        )

        set_last_commit(state, after_commit)

        if validation_ok:
            increment_tasks(state)

            if mode == "audit":
                mark_audit_complete(state)

                n = extract_and_save_findings(
                    claude_output=result.stdout,
                    mode=mode,
                )

                if n:
                    print(f"\nAUDIT: saved {n} finding(s)")

            print("\nVALIDATION PASSED")

        else:
            print("\nVALIDATION FAILED")
            print(validation_reason)

        heartbeat(state)

        save_state(state, STATE_FILE)

        write_state_md(
            task=task,
            result_stdout=result.stdout,
            result_stderr=result.stderr,
            repo=repo_after,
            validation_ok=validation_ok,
            validation_reason=validation_reason,
        )

        print("\nTOTAL TASKS:", state["tasks_completed"])

        time.sleep(10)


if __name__ == "__main__":
    main()
