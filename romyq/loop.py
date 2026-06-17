import os
import time

from . import manager, runner, workspace as ws
from .findings import extract_from_output
from .history import add_entry
from .mission import load
from .state import (
    load as load_state,
    save as save_state,
    heartbeat,
    set_current_task,
    increment_tasks,
    set_last_commit,
    next_mode,
    mark_audit_complete,
    mark_completed,
)
from .validator import validate


STATE_FILE = "state.json"
STATE_MD = "state.md"


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _write_state_md(
    task: str,
    stdout: str,
    stderr: str,
    repo: dict,
    ok: bool,
    reason: str,
) -> None:
    with open(STATE_MD, "w") as f:
        f.write(
            f"# Current State\n\n"
            f"## Last Task\n\n{task}\n\n"
            f"## Last Commit\n\n{repo['latest_commit']}\n\n"
            f"## Validation\n\nSuccess: {ok}\n\nReason: {reason}\n\n"
            f"## Git Status\n\n{repo['git_status']}\n\n"
            f"## Repository Changes\n\n{repo['diff_stat']}\n\n"
            f"## Claude Output\n\n{stdout}\n\n"
            f"## Claude Errors\n\n{stderr}\n"
        )


def run(workspace_path: str) -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set. Add it to .env or your environment.")

    ws.bootstrap(workspace_path)

    while True:
        state = load_state(STATE_FILE)
        heartbeat(state)

        mission = load()
        state_text = _read(STATE_MD)
        repo_before = ws.inspect(workspace_path)

        if state["tasks_completed"] > 0:
            completed, reason = manager.evaluate_completion(
                api_key=api_key,
                mission=mission,
                workspace=workspace_path,
                git_log=repo_before["git_log"],
            )

            print("\n" + "=" * 72)
            print(f"COMPLETION CHECK  completed={completed}")
            print(f"  {reason}")
            print("=" * 72)

            if completed:
                mark_completed(state)
                heartbeat(state)
                save_state(state, STATE_FILE)
                print("\nMISSION COMPLETE —", reason)
                break

        mode = next_mode(state)

        task = manager.generate_task(
            api_key=api_key,
            mission=mission,
            state=state_text,
            tasks_completed=state["tasks_completed"],
            git_log=repo_before["git_log"],
            git_status=repo_before["git_status"],
            mode=mode,
            workspace=workspace_path,
        )

        print("\n" + "=" * 72)
        print(f"MODE: {mode}")
        print("=" * 72)
        print(task)
        print("=" * 72)

        set_current_task(state, task)
        save_state(state, STATE_FILE)

        before_commit = repo_before["latest_commit"]

        result = runner.run_with_retry(workspace=workspace_path, task=task)

        repo_after = ws.inspect(workspace_path)
        after_commit = repo_after["latest_commit"]

        ok, reason = validate(
            workspace=workspace_path,
            before_commit=before_commit,
            after_commit=after_commit,
            returncode=result.returncode,
        )

        add_entry(
            task=task,
            mode=mode,
            success=ok,
            commit=after_commit,
            validation_reason=reason,
        )

        set_last_commit(state, after_commit)

        if ok:
            increment_tasks(state)

            if mode == "audit":
                mark_audit_complete(state)
                n = extract_from_output(result.stdout, mode)
                if n:
                    print(f"\nAUDIT: saved {n} finding(s)")

            print("\nVALIDATION PASSED")
        else:
            print(f"\nVALIDATION FAILED: {reason}")

        heartbeat(state)
        save_state(state, STATE_FILE)
        _write_state_md(task, result.stdout, result.stderr, repo_after, ok, reason)

        print(f"\nTOTAL TASKS: {state['tasks_completed']}")

        time.sleep(10)
