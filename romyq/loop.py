from __future__ import annotations

import hashlib
import os
import subprocess
import time
from datetime import datetime, timezone

from . import activity, manager, notes, store, workspace as ws
from .findings import add_finding, extract_from_output
from .history import add_entry
from .mission import load
from .runner import (
    ClaudeRateLimitError,
    ClaudeTimeoutError,
    run as run_claude,
    _DEFAULT_WAIT_SECONDS,
)
from .state import (
    clear_rate_limit,
    heartbeat,
    increment_tasks,
    load as load_state,
    mark_audit_complete,
    mark_completed,
    mark_stopped,
    next_mode,
    refresh_control_flags,
    save as save_state,
    set_current_task,
    set_last_commit,
    set_rate_limited,
)
from .validator import validate


# ── failure thresholds ────────────────────────────────────────────────────────

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


def _sleep_chunked(total_seconds: int, state_path: str) -> bool:
    """Sleep for total_seconds, waking every 30 s to check stop_requested.

    Returns True if a stop was requested during the sleep.
    """
    deadline = time.monotonic() + total_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(30.0, remaining))
        try:
            if load_state(state_path).get("stop_requested"):
                return True
        except Exception:
            pass
    return False


# ── main loop ─────────────────────────────────────────────────────────────────

def run(workspace_path: str, until_complete: bool = False) -> None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY is not set. Add it to .env or your environment.")

    ws.bootstrap(workspace_path)

    moved = store.migrate(workspace_path)
    for desc in moved:
        activity.log(f"Migrated: {desc}")

    s_path = store.state_path(workspace_path)
    h_path = store.history_path(workspace_path)
    f_path = store.findings_path(workspace_path)
    md_path = store.state_md_path(workspace_path)

    timeout_s = int(os.getenv("ROMYQ_CLAUDE_TIMEOUT", str(60 * 30)))
    activity.log(f"Romyq started. Claude timeout: {timeout_s // 60}m.")

    def _heartbeat_cb(elapsed: int) -> None:
        remaining = max(0, timeout_s - elapsed)
        e_fmt = f"{elapsed // 60}m{elapsed % 60:02d}s" if elapsed >= 60 else f"{elapsed}s"
        r_fmt = f"{remaining // 60}m{remaining % 60:02d}s" if remaining >= 60 else f"{remaining}s"
        activity.log(f"Claude running ({e_fmt} elapsed, {r_fmt} remaining)")

    # In-memory failure tracking (resets on restart).
    same_task_streak: int = 0
    last_failed_key: str | None = None
    consecutive_failures: int = 0
    in_diagnosis: bool = False
    diagnosis_failures: int = 0

    # When set, this task is retried after a rate-limit wake without a new
    # DeepSeek call.  The key for this task is stored in pending_task_key.
    pending_task: str | None = None
    pending_task_key: str | None = None

    while True:
        state = load_state(s_path)
        heartbeat(state)

        # ── stop check ────────────────────────────────────────────────────────
        if state.get("stop_requested"):
            activity.log("Stop requested — exiting gracefully.")
            mark_stopped(state)
            save_state(state, s_path)
            break

        # ── pause check (blocking) ────────────────────────────────────────────
        if state.get("paused"):
            activity.log("Paused — waiting for 'romyq resume'…")
            save_state(state, s_path)
            while True:
                time.sleep(30)
                state = load_state(s_path)
                heartbeat(state)
                save_state(state, s_path)
                if state.get("stop_requested"):
                    activity.log("Stop requested while paused — exiting.")
                    mark_stopped(state)
                    save_state(state, s_path)
                    return
                if not state.get("paused"):
                    activity.log("Resumed.")
                    break

        # ── mission & state setup ─────────────────────────────────────────────
        mission = load()
        state_text = _read(md_path)
        repo_before = ws.inspect(workspace_path)
        mode = next_mode(state)
        task_num = state["tasks_completed"] + 1

        # ── completion check (skip when retrying after rate limit) ────────────
        if pending_task is None:
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
        if pending_task is not None:
            task = pending_task
            key = pending_task_key  # ← Finding 4: always carry the key forward
            pending_task = None
            pending_task_key = None
            activity.log(f"Task {task_num}  mode={mode}  (retrying after rate limit)")
            print(f"\n{task}\n")

        elif in_diagnosis:
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
                notes=notes.load(store.notes_path(workspace_path)),
            )
            activity.log("Task generated.")
            key = _task_key(task)

            if key == last_failed_key and same_task_streak >= _SAME_TASK_THRESHOLD:
                activity.log(f"Task has failed {same_task_streak} times — switching to diagnosis mode.")
                task = _make_diagnosis_task(task, same_task_streak)
                key = "__diagnosis__"
                mode = "audit"
                in_diagnosis = True

            print(f"\n{task}\n")

        set_current_task(state, task)
        activity.log("Saving state...")
        # Finding 1: re-read control flags before saving so a CLI pause/stop
        # issued during task-generation is not silently overwritten.
        refresh_control_flags(state, s_path)
        save_state(state, s_path)
        activity.log("State saved.")

        before_commit = repo_before["latest_commit"]
        pre_dirty = bool(repo_before["git_status"].strip())
        # Finding 3: capture the exact set of pre-existing dirty paths so the
        # validator can selectively restore only Claude's changes on failure.
        pre_dirty_paths: frozenset = ws.dirty_files(workspace_path) if pre_dirty else frozenset()
        if pre_dirty:
            activity.log(
                "Warning: pre-existing uncommitted changes detected. "
                "Claude's changes will be selectively restored on failure; "
                "your existing changes will be preserved."
            )

        # ── run Claude ────────────────────────────────────────────────────────
        activity.log("Launching Claude...")
        t_start = time.monotonic()
        timed_out = False

        try:
            result = run_claude(
                workspace=workspace_path,
                task=task,
                on_heartbeat=_heartbeat_cb,
                timeout_seconds=timeout_s,
            )

        except ClaudeRateLimitError as e:
            # ── rate-limit handling ───────────────────────────────────────────
            activity.log("Claude rate limit detected.")

            if e.reset_at is not None:
                wait_s = max(60, int((e.reset_at - datetime.now(timezone.utc)).total_seconds()))
                tz_label = e.tz_name or "UTC"
                display = e.reset_display or e.reset_at.strftime("%H:%M")
                activity.log(f"Reset at {display} {tz_label}.")
                activity.log(f"Sleeping until reset ({wait_s // 60}m {wait_s % 60:02d}s).")
                resume_iso = e.reset_at.isoformat()
            else:
                from datetime import timedelta
                wait_s = _DEFAULT_WAIT_SECONDS
                activity.log("Reset time unknown — sleeping 30 minutes.")
                resume_iso = (datetime.now(timezone.utc) + timedelta(seconds=wait_s)).isoformat()

            set_rate_limited(state, resume_iso)
            heartbeat(state)
            # Finding 1: refresh before save — a CLI stop issued between task
            # generation and this point must not be discarded.
            refresh_control_flags(state, s_path)
            save_state(state, s_path)

            stopped = _sleep_chunked(wait_s, s_path)

            clear_rate_limit(state)
            heartbeat(state)
            refresh_control_flags(state, s_path)
            save_state(state, s_path)

            if stopped:
                activity.log("Stop requested during rate-limit sleep — exiting.")
                mark_stopped(state)
                save_state(state, s_path)
                break

            # Retry the same task — do not generate a new DeepSeek task.
            # Store the key alongside the task so Finding 4 is avoided.
            pending_task = task
            pending_task_key = key
            activity.log("Rate-limit sleep complete. Retrying task.")
            continue

        except ClaudeTimeoutError as e:
            timed_out = True
            result = subprocess.CompletedProcess(
                args=["claude"],
                returncode=1,
                stdout="",
                stderr=f"Claude timed out: {e}",
            )

        elapsed = int(time.monotonic() - t_start)
        if timed_out:
            activity.log(f"Claude timed out ({elapsed}s).")
        else:
            activity.log(f"Claude done ({elapsed}s).")

        repo_after = ws.inspect(workspace_path)
        after_commit = repo_after["latest_commit"]

        activity.log("Validating...")
        ok, reason = validate(
            workspace=workspace_path,
            before_commit=before_commit,
            after_commit=after_commit,
            returncode=result.returncode,
            # Finding 2: pass stdout so validator can honour the COMPLETED marker.
            stdout=result.stdout,
            # Finding 3: pass pre-existing dirty paths for selective restore.
            pre_dirty=pre_dirty,
            pre_dirty_paths=pre_dirty_paths,
        )

        if not ok and timed_out:
            reason = f"Claude timed out after {elapsed}s ({timeout_s}s limit)"

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
            activity.log(f"Diagnosis failed ({diagnosis_failures}/{_DIAGNOSIS_GIVEUP}) — {reason}")

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
        # Finding 1: re-read control flags immediately before the end-of-iteration
        # save.  This is the most critical refresh point — Claude may have run
        # for 30 minutes and any CLI pause/stop written during that window would
        # otherwise be silently overwritten by the stale in-memory dict.
        refresh_control_flags(state, s_path)
        save_state(state, s_path)
        _write_state_md(md_path, task, result.stdout, result.stderr, repo_after, ok, reason)
        activity.log(f"State saved. Tasks completed: {state['tasks_completed']}")

        activity.log("Waiting 10s before next task...")
        time.sleep(10)
