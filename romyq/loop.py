import hashlib
import os
import time

from . import activity, manager, runner, store, workspace as ws
from .findings import add_finding, extract_from_output
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


# Failure thresholds
_SAME_TASK_THRESHOLD = 3    # same task key fails this many times → diagnosis
_DIAGNOSIS_GIVEUP = 3       # diagnosis fails this many times → record finding + reset
_CONSECUTIVE_THRESHOLD = 8  # any-task consecutive failures → record finding + reset

_DIAGNOSIS_TASK = """\
DIAGNOSIS: The following task has failed {n} consecutive times and progress is blocked.

Stuck task:
{context}

Your job:

1. Review git log and repository state carefully.
2. Identify what is blocking progress — look for broken code, failed tests,
   missing dependencies, config errors, or incorrect assumptions.
3. Fix the most fundamental blocking issue you find.
4. Commit the fix with a clear message explaining what was broken.

If nothing can be committed, create or update BLOCKERS.md documenting
what is preventing progress and why, then commit that file.
"""


def _make_diagnosis_task(stuck_task: str, n: int) -> str:
    context = stuck_task[:600] + ("..." if len(stuck_task) > 600 else "")
    return _DIAGNOSIS_TASK.format(n=n, context=context)


def _task_key(task: str) -> str:
    return hashlib.md5(task.encode()).hexdigest()[:12]


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _write_state_md(
    path: str,
    task: str,
    stdout: str,
    stderr: str,
    repo: dict,
    ok: bool,
    reason: str,
) -> None:
    with open(path, "w") as f:
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

    # Migrate any legacy CWD-based state files on first run
    moved = store.migrate(workspace_path)
    for desc in moved:
        activity.log(f"Migrated: {desc}")

    # Derive workspace-scoped paths
    s_path = store.state_path(workspace_path)
    h_path = store.history_path(workspace_path)
    f_path = store.findings_path(workspace_path)
    md_path = store.state_md_path(workspace_path)

    activity.log("Romyq started.")

    # Failure tracking (in-memory; resets on restart)
    same_task_streak: int = 0
    last_failed_key: str | None = None
    consecutive_failures: int = 0
    in_diagnosis: bool = False
    diagnosis_failures: int = 0

    while True:
        state = load_state(s_path)
        heartbeat(state)

        mission = load()
        state_text = _read(md_path)
        repo_before = ws.inspect(workspace_path)

        mode = next_mode(state)
        task_num = state["tasks_completed"] + 1

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
                save_state(state, s_path)
                if until_complete:
                    break
                activity.log("Continuous mode — proceeding with improvements.")
            else:
                activity.log(f"Continuing — {reason}")

        # ── task selection ────────────────────────────────────────────────────

        if in_diagnosis:
            mode = "audit"
            task = _make_diagnosis_task(state.get("current_task", ""), same_task_streak)
            key = "__diagnosis__"
            activity.log(
                f"Task {task_num}  mode=diagnosis  "
                f"(attempt {diagnosis_failures + 1}/{_DIAGNOSIS_GIVEUP})"
            )
            print(f"\n{task}\n")
        else:
            activity.log(f"Task {task_num}  mode={mode}")
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
            key = _task_key(task)

            if key == last_failed_key and same_task_streak >= _SAME_TASK_THRESHOLD:
                activity.log(
                    f"Task has failed {same_task_streak} times — switching to diagnosis mode."
                )
                task = _make_diagnosis_task(task, same_task_streak)
                key = "__diagnosis__"
                mode = "audit"
                in_diagnosis = True

            print(f"\n{task}\n")

        set_current_task(state, task)
        activity.log("Saving state...")
        save_state(state, s_path)
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
            path=h_path,
        )

        set_last_commit(state, after_commit)

        # ── failure tracking ──────────────────────────────────────────────────

        if ok:
            if in_diagnosis:
                activity.log("Diagnosis task succeeded — resuming normal operation.")
            same_task_streak = 0
            last_failed_key = None
            consecutive_failures = 0
            in_diagnosis = False
            diagnosis_failures = 0

            increment_tasks(state)

            if mode == "audit":
                mark_audit_complete(state)
                n = extract_from_output(result.stdout, mode, path=f_path)
                if n:
                    activity.log(f"Audit saved {n} finding(s).")

        elif in_diagnosis:
            diagnosis_failures += 1
            activity.log(
                f"Diagnosis failed ({diagnosis_failures}/{_DIAGNOSIS_GIVEUP}) — {reason}"
            )

            if diagnosis_failures >= _DIAGNOSIS_GIVEUP:
                activity.log("Diagnosis exhausted — recording finding and moving on.")
                add_finding(
                    title="Repeated failure: progress blocked",
                    description=(
                        f"Task failed {same_task_streak} consecutive times. "
                        f"Diagnosis also failed {diagnosis_failures} times.\n"
                        f"Last failure: {reason}"
                    ),
                    severity="high",
                    path=f_path,
                )
                same_task_streak = 0
                last_failed_key = None
                consecutive_failures = 0
                in_diagnosis = False
                diagnosis_failures = 0

        else:
            consecutive_failures += 1

            if key == last_failed_key:
                same_task_streak += 1
            else:
                same_task_streak = 1
                last_failed_key = key

            activity.log(
                f"Failure streak: {same_task_streak} same-task, "
                f"{consecutive_failures} consecutive."
            )

            if consecutive_failures >= _CONSECUTIVE_THRESHOLD:
                activity.log(
                    f"Too many consecutive failures ({consecutive_failures}) — "
                    "recording finding and resetting."
                )
                add_finding(
                    title=f"Repeated failures: {consecutive_failures} consecutive",
                    description=(
                        f"Multiple consecutive failures across different tasks.\n"
                        f"Last failure: {reason}"
                    ),
                    severity="high",
                    path=f_path,
                )
                consecutive_failures = 0
                same_task_streak = 0
                last_failed_key = None

        # ── state persistence ─────────────────────────────────────────────────

        activity.log("Saving state...")
        heartbeat(state)
        save_state(state, s_path)
        _write_state_md(md_path, task, result.stdout, result.stderr, repo_after, ok, reason)
        activity.log(f"State saved. Tasks completed: {state['tasks_completed']}")

        activity.log("Waiting 10s before next task...")
        time.sleep(10)
