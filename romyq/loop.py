import os
import time

from . import activity, manager, runner, workspace as ws
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


def run(workspace_path: str, until_complete: bool = False) -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set. Add it to .env or your environment.")

    ws.bootstrap(workspace_path)
    activity.log("Romyq started.")

    while True:
        state = load_state(STATE_FILE)
        heartbeat(state)

        mission = load()
        state_text = _read(STATE_MD)
        repo_before = ws.inspect(workspace_path)

        mode = next_mode(state)
        task_num = state["tasks_completed"] + 1
        activity.log(f"Task {task_num}  mode={mode}")

        already_complete = state["status"] == "completed"
        run_check = state["tasks_completed"] > 0 and (until_complete or not already_complete)

        if run_check:
            activity.log("Checking mission completion...")
            completed, reason = manager.evaluate_completion(
                api_key=api_key,
                mission=mission,
                workspace=workspace_path,
                git_log=repo_before["git_log"],
            )

            if completed:
                activity.log(f"Mission complete — {reason}")
                mark_completed(state)
                heartbeat(state)
                save_state(state, STATE_FILE)
                if until_complete:
                    break
                activity.log("Continuous mode — proceeding with improvements.")
            else:
                activity.log(f"Continuing — {reason}")

        activity.log("Asking DeepSeek...")
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
        activity.log("Task generated.")
        print(f"\n{task}\n")

        set_current_task(state, task)
        activity.log("Saving state...")
        save_state(state, STATE_FILE)
        activity.log("State saved.")

        before_commit = repo_before["latest_commit"]

        activity.log("Launching Claude...")
        t_start = time.monotonic()
        result = runner.run_with_retry(
            workspace=workspace_path,
            task=task,
            on_heartbeat=lambda s: activity.log(f"Claude running ({s}s)"),
        )
        elapsed = int(time.monotonic() - t_start)
        activity.log(f"Claude done ({elapsed}s).")

        repo_after = ws.inspect(workspace_path)
        after_commit = repo_after["latest_commit"]

        activity.log("Validating...")
        ok, reason = validate(
            workspace=workspace_path,
            before_commit=before_commit,
            after_commit=after_commit,
            returncode=result.returncode,
        )

        if ok:
            activity.log("Validation passed.")
        else:
            activity.log(f"Validation failed — {reason}")

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
                    activity.log(f"Audit saved {n} finding(s).")

        activity.log("Saving state...")
        heartbeat(state)
        save_state(state, STATE_FILE)
        _write_state_md(task, result.stdout, result.stderr, repo_after, ok, reason)
        activity.log(f"State saved. Tasks completed: {state['tasks_completed']}")

        activity.log("Waiting 10s before next task...")
        time.sleep(10)
