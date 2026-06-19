from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from datetime import datetime, timezone

from . import activity, manager, notes, store, workspace as ws
from .cancel import CancellationToken
from . import fingerprint as fp_mod
from . import memory as mem_mod
from .events import emit, prune as prune_events
from . import events as ev
from .findings import add_finding, extract_from_output
from .history import add_entry
from .mission import load
from .runner import (
    ClaudeCancelledError,
    ClaudeRateLimitError,
    ClaudeTimeoutError,
    run as run_claude,
    _DEFAULT_WAIT_SECONDS,
)
from .runstate import RunState
from .state import (
    clear_rate_limit,
    heartbeat,
    increment_tasks,
    is_task_blocked,
    load as load_state,
    mark_audit_complete,
    mark_completed,
    mark_stopped,
    next_mode,
    record_task_failure,
    record_task_success,
    refresh_control_flags,
    save as save_state,
    set_current_task,
    set_last_commit,
    set_phase,
    set_rate_limited,
)
from .validator import FAILURE, NO_ACTION_REQUIRED, SUCCESS, rollback, validate


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
    return fp_mod.fingerprint(task)


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
    evidence: list[str] | None = None,
) -> None:
    evidence_section = ""
    if evidence:
        evidence_section = "\n## Validation Evidence\n\n" + "\n".join(evidence[:50]) + "\n"
    content = (
        f"# Current State\n\n"
        f"## Last Task\n\n{task}\n\n"
        f"## Last Commit\n\n{repo['latest_commit']}\n\n"
        f"## Validation\n\nSuccess: {ok}\n\nReason: {reason}\n"
        f"{evidence_section}"
        f"\n## Git Status\n\n{repo['git_status']}\n\n"
        f"## Repository Changes\n\n{repo['diff_stat']}\n\n"
        f"## Claude Output\n\n{stdout}\n\n"
        f"## Claude Errors\n\n{stderr}\n"
    )
    dir_ = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8") as f:
        f.write(content)
        f.flush()
        os.fsync(f.fileno())
        tmp = f.name
    os.replace(tmp, path)


# ── main loop ─────────────────────────────────────────────────────────────────

_LIVE_REFRESH_INTERVAL = 25   # regenerate knowledge every N new memory entries


def _approval_prompt(task: str) -> str:
    """Ask user to approve/reject the proposed task. Returns 'approve' or 'reject'."""
    print("\n" + "═" * 60)
    print("APPROVAL REQUIRED")
    print("═" * 60)
    print("Proposed task:\n")
    for line in task.splitlines()[:20]:
        print(f"  {line}")
    if len(task.splitlines()) > 20:
        print("  ...")
    print()
    while True:
        try:
            answer = input("  [A]pprove  [R]eject  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            return "reject"
        if answer in ("a", "approve", "y", "yes"):
            return "approve"
        if answer in ("r", "reject", "n", "no"):
            return "reject"
        print("  Enter A to approve or R to reject.")


def run(workspace_path: str, until_complete: bool = False, approval_mode: bool = False) -> None:
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
    e_path = store.events_path(workspace_path)
    mem_path = store.memory_path(workspace_path)
    know_path = store.knowledge_path(workspace_path)
    plan_path = store.plan_path(workspace_path)

    timeout_s = int(os.getenv("ROMYQ_CLAUDE_TIMEOUT", str(60 * 30)))
    activity.log(f"Romyq started. Claude timeout: {timeout_s // 60}m.")

    # Single CancellationToken for the entire session.
    cancel_token = CancellationToken(s_path)

    # ── signal handling ───────────────────────────────────────────────────────
    # On SIGTERM/SIGINT, set stop_requested so the cancel_token fires on the
    # next poll.  This ensures Claude is terminated, the workspace is rolled
    # back, and a LOOP_STOPPED event is written before exit.
    def _handle_signal(signum: int, frame: object) -> None:
        activity.log(f"Signal {signum} received — requesting stop.")
        try:
            state = load_state(s_path)
            state["stop_requested"] = True
            save_state(state, s_path)
        except Exception:
            pass

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    emit(e_path, ev.LOOP_STARTED, timeout_s=timeout_s)
    _max_events = int(os.getenv("ROMYQ_MAX_EVENTS", "10000"))
    prune_events(e_path, max_entries=_max_events)

    # Auto-generate .romyq/context.md if absent (or if ROMYQ_REFRESH_CONTEXT=1).
    _ctx_text = ""
    try:
        from . import context as _ctx_mod
        from .store import context_path as _ctx_path_fn
        import pathlib as _pathlib
        _ctx_path = _ctx_path_fn(workspace_path)
        _refresh = os.getenv("ROMYQ_REFRESH_CONTEXT", "0") == "1"
        if _refresh or not _pathlib.Path(_ctx_path).exists():
            _ctx_mod.write(workspace_path)
            activity.log("Repository context written to .romyq/context.md")
        _ctx_text = _ctx_mod.load(workspace_path)
    except Exception:
        pass

    # Refresh .romyq/knowledge.json if stale (or if ROMYQ_REFRESH_CONTEXT=1).
    try:
        from . import knowledge as _know_mod
        from .store import knowledge_path as _know_path_fn
        _know_path = _know_path_fn(workspace_path)
        _refresh_know = (
            os.getenv("ROMYQ_REFRESH_CONTEXT", "0") == "1"
            or _know_mod.is_stale(_know_path, mem_path, store.history_path(workspace_path), _ctx_text)
        )
        if _refresh_know:
            _know_mod.write(
                _know_path,
                mem_path,
                store.history_path(workspace_path),
                e_path,
                _ctx_text,
            )
            emit(e_path, ev.CONTEXT_REFRESHED)
            activity.log("Knowledge base refreshed: .romyq/knowledge.json")
    except Exception:
        pass

    # Generate mission plan if not already present.
    try:
        import pathlib as _pl
        from . import decomposition as _dec_mod
        if not _pl.Path(plan_path).exists():
            mission_for_plan = load()
            plan_data = _dec_mod.decompose(api_key, mission_for_plan)
            _dec_mod.write_plan(plan_path, plan_data)
            task_count = len(plan_data.get("tasks", []))
            activity.log(f"Mission plan generated: {task_count} tasks in .romyq/plan.json")
    except Exception:
        pass

    # Track memory entry count for live knowledge refresh.
    _mem_entries_at_start = 0
    try:
        from . import knowledge as _know_mod2
        _mem_entries_at_start = _know_mod2._count_memory_entries(mem_path)
    except Exception:
        pass

    def _maybe_refresh_knowledge() -> None:
        """Regenerate knowledge.json if 25+ new entries since last refresh."""
        try:
            from . import knowledge as _km
            from .health_checks import detect_recurring_failures as _drf
            nonlocal _mem_entries_at_start
            current_count = _km._count_memory_entries(mem_path)
            new_entries = current_count - _mem_entries_at_start
            recurring = _drf(h_path)
            if new_entries >= _LIVE_REFRESH_INTERVAL or recurring:
                _km.write(know_path, mem_path, h_path, e_path, _ctx_text)
                emit(e_path, ev.KNOWLEDGE_REFRESHED,
                     new_entries=new_entries,
                     recurring_failures=bool(recurring))
                activity.log("Knowledge base refreshed mid-session.")
                _mem_entries_at_start = current_count
        except Exception:
            pass

    def _heartbeat_cb(elapsed: int) -> None:
        remaining = max(0, timeout_s - elapsed)
        e_fmt = f"{elapsed // 60}m{elapsed % 60:02d}s" if elapsed >= 60 else f"{elapsed}s"
        r_fmt = f"{remaining // 60}m{remaining % 60:02d}s" if remaining >= 60 else f"{remaining}s"
        activity.log(f"Claude running ({e_fmt} elapsed, {r_fmt} remaining)")

    # ── in-memory failure tracking (supplements persistent tracking) ──────────
    same_task_streak: int = 0
    last_failed_key: str | None = None
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
            emit(e_path, ev.STOP_DETECTED)
            set_phase(state, RunState.STOPPING)
            mark_stopped(state)
            set_phase(state, RunState.STOPPED)
            save_state(state, s_path)
            emit(e_path, ev.LOOP_STOPPED, reason="stop_requested")
            break

        # ── pause check (blocking poll) ───────────────────────────────────────
        if state.get("paused"):
            activity.log("Paused — waiting for 'romyq resume'…")
            set_phase(state, RunState.PAUSED)
            save_state(state, s_path)
            emit(e_path, ev.PAUSE_DETECTED)
            while True:
                time.sleep(5)
                state = load_state(s_path)
                heartbeat(state)
                save_state(state, s_path)
                if state.get("stop_requested"):
                    activity.log("Stop requested while paused — exiting.")
                    emit(e_path, ev.STOP_DETECTED)
                    mark_stopped(state)
                    set_phase(state, RunState.STOPPED)
                    save_state(state, s_path)
                    emit(e_path, ev.LOOP_STOPPED, reason="stop_requested_while_paused")
                    return
                if not state.get("paused"):
                    activity.log("Resumed.")
                    emit(e_path, ev.RESUME_DETECTED)
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
                set_phase(state, RunState.PLANNING)
                save_state(state, s_path)
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
                        emit(e_path, ev.LOOP_STOPPED, reason="mission_complete")
                        break
                    activity.log("Continuous mode — proceeding with improvements.")
                else:
                    activity.log(f"Continuing — {reason}")

        # ── task selection ────────────────────────────────────────────────────
        set_phase(state, RunState.PLANNING)

        if pending_task is not None:
            task = pending_task
            key = pending_task_key
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
            # Check persistent block: has this task failed too many times?
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
                state_dict=state,
            )
            activity.log("Task generated.")
            key = _task_key(task)

            # Memory check: warn if this task fingerprint has prior failures.
            prior_text = mem_mod.prior_outcomes_text(mem_path, task)
            if prior_text:
                activity.log(
                    f"Memory: task fp={key[:8]} has prior failures — "
                    "injecting failure context for Claude."
                )
                task = task + "\n\n" + prior_text

            if is_task_blocked(state, key):
                attempts = state.get("current_task_attempts", 0)
                last_reason = state.get("last_failure_reason", "unknown")
                activity.log(
                    f"Task is BLOCKED after {attempts} attempts — "
                    f"last failure: {last_reason}"
                )
                emit(e_path, ev.TASK_BLOCKED, key=key, attempts=attempts, last_reason=last_reason)
                add_finding(
                    title=f"Task blocked after {attempts} attempts",
                    description=(
                        f"Task key: {key}\n"
                        f"Attempts: {attempts}\n"
                        f"Last failure: {last_reason}\n"
                        f"Task preview: {task[:300]}"
                    ),
                    severity="high",
                    path=f_path,
                )
                # Reset the block so the loop can generate a different task next time
                record_task_success(state)
                save_state(state, s_path)
                continue

            # Guardrail check: reject tasks matching known failure patterns
            try:
                from .planning_guardrails import validate_task_against_knowledge
                from . import events as _ev_mod
                violation = validate_task_against_knowledge(task, know_path, mem_path)
                if violation:
                    activity.log(f"Guardrail triggered: {violation.reason[:80]}")
                    emit(e_path, _ev_mod.GUARDRAIL_TRIGGERED,
                         fingerprint=violation.fingerprint,
                         reason=violation.reason[:200])
            except Exception:
                pass

            if key == last_failed_key and same_task_streak >= _SAME_TASK_THRESHOLD:
                activity.log(f"Task has failed {same_task_streak} times — switching to diagnosis mode.")
                task = _make_diagnosis_task(task, same_task_streak)
                key = "__diagnosis__"
                mode = "audit"
                in_diagnosis = True

            print(f"\n{task}\n")

        set_current_task(state, task)
        activity.log("Saving state...")
        refresh_control_flags(state, s_path)
        save_state(state, s_path)
        activity.log("State saved.")

        before_commit = repo_before["latest_commit"]
        pre_dirty = bool(repo_before["git_status"].strip())
        pre_dirty_paths: frozenset = ws.dirty_files(workspace_path) if pre_dirty else frozenset()
        if pre_dirty:
            activity.log(
                "Warning: pre-existing uncommitted changes detected. "
                "Claude's changes will be selectively restored on failure; "
                "your existing changes will be preserved."
            )

        # ── approval mode ─────────────────────────────────────────────────────
        if approval_mode and not in_diagnosis and pending_task is None:
            decision = _approval_prompt(task)
            if decision == "reject":
                activity.log("Task rejected by operator — requesting new task from planner.")
                emit(e_path, ev.TASK_REJECTED, key=key, reason="operator_rejected")
                continue  # back to top to generate a new task

            emit(e_path, ev.TASK_APPROVED, key=key)
            activity.log("Task approved by operator.")

        emit(e_path, ev.TASK_STARTED, key=key, mode=mode, task_preview=task[:120])

        # ── run Claude ────────────────────────────────────────────────────────
        activity.log("Launching Claude...")
        set_phase(state, RunState.EXECUTING)
        heartbeat(state)
        save_state(state, s_path)

        t_start = time.monotonic()
        timed_out = False
        cancelled = False

        try:
            result = run_claude(
                workspace=workspace_path,
                task=task,
                on_heartbeat=_heartbeat_cb,
                timeout_seconds=timeout_s,
                cancel_token=cancel_token,
            )

        except ClaudeCancelledError:
            activity.log("Claude cancelled by stop request.")
            emit(e_path, ev.CLAUDE_CANCELLED)
            rollback(workspace_path, pre_dirty=pre_dirty, pre_dirty_paths=pre_dirty_paths)
            activity.log("Workspace restored after cancellation.")
            emit(e_path, ev.LOOP_STOPPED, reason="cancelled_during_execution")
            state = load_state(s_path)
            mark_stopped(state)
            set_phase(state, RunState.STOPPED)
            save_state(state, s_path)
            return

        except ClaudeRateLimitError as e:
            # ── rate-limit handling ───────────────────────────────────────────
            activity.log("Claude rate limit detected.")
            emit(e_path, ev.RATE_LIMIT_DETECTED,
                 reset_display=e.reset_display, tz_name=e.tz_name)

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
            set_phase(state, RunState.RATE_LIMITED)
            heartbeat(state)
            refresh_control_flags(state, s_path)
            save_state(state, s_path)

            stopped = cancel_token.wait(wait_s)

            clear_rate_limit(state)
            heartbeat(state)
            refresh_control_flags(state, s_path)
            save_state(state, s_path)
            emit(e_path, ev.RATE_LIMIT_RECOVERED)

            if stopped:
                activity.log("Stop requested during rate-limit sleep — exiting.")
                emit(e_path, ev.LOOP_STOPPED, reason="stop_during_rate_limit")
                mark_stopped(state)
                set_phase(state, RunState.STOPPED)
                save_state(state, s_path)
                break

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

        # ── validate ──────────────────────────────────────────────────────────
        activity.log("Validating...")
        set_phase(state, RunState.VALIDATING)
        heartbeat(state)
        save_state(state, s_path)

        repo_after = ws.inspect(workspace_path)
        after_commit = repo_after["latest_commit"]

        vr = validate(
            workspace=workspace_path,
            before_commit=before_commit,
            after_commit=after_commit,
            returncode=result.returncode,
            stdout=result.stdout,
            pre_dirty=pre_dirty,
            pre_dirty_paths=pre_dirty_paths,
        )
        outcome = vr.outcome
        reason = vr.reason
        evidence = vr.evidence

        if outcome == FAILURE and timed_out:
            reason = f"Claude timed out after {elapsed}s ({timeout_s}s limit)"

        if outcome == SUCCESS:
            activity.log("Validation passed.")
            emit(e_path, ev.VALIDATOR_PASSED, key=key, commit=after_commit)
        elif outcome == NO_ACTION_REQUIRED:
            activity.log("Task already complete — no action required.")
            emit(e_path, ev.NO_ACTION_REQUIRED, key=key)
        else:
            activity.log(f"Validation failed — {reason}")
            emit(e_path, ev.VALIDATOR_FAILED, key=key, reason=reason)

        add_entry(
            task=task,
            mode=mode,
            success=(outcome != FAILURE),
            commit=after_commit,
            validation_reason=reason,
            path=h_path,
        )

        mission_fp = fp_mod.fingerprint(mission)
        try:
            mem_mod.record(
                path=mem_path,
                task=task,
                mission_fp=mission_fp,
                outcome=outcome,
                evidence=evidence[:5],
                failure_reason=reason if outcome == FAILURE else "",
                retry_count=state.get("current_task_attempts", 0),
            )
            mem_mod.update_mission(
                path=mem_path,
                mission_fp=mission_fp,
                preview=mission[:120],
                completed=(outcome != FAILURE),
                blocked=is_task_blocked(state, key),
            )
        except Exception:
            pass

        # Live knowledge refresh (every 25 new entries or recurring failures)
        _maybe_refresh_knowledge()

        set_last_commit(state, after_commit)
        state["last_validation_evidence"] = evidence[:30]  # cap stored evidence

        # ── failure / success tracking ────────────────────────────────────────
        if outcome != FAILURE:
            if in_diagnosis:
                activity.log("Diagnosis task succeeded — resuming normal operation.")
            same_task_streak = 0
            last_failed_key = None
            in_diagnosis = False
            diagnosis_failures = 0

            record_task_success(state)
            increment_tasks(state)
            emit(e_path, ev.TASK_COMPLETED, key=key, outcome=outcome)

            if mode == "audit":
                mark_audit_complete(state)
                if outcome == SUCCESS:
                    n = extract_from_output(result.stdout, mode, path=f_path)
                    if n:
                        activity.log(f"Audit saved {n} finding(s).")

        elif in_diagnosis:
            diagnosis_failures += 1
            activity.log(f"Diagnosis failed ({diagnosis_failures}/{_DIAGNOSIS_GIVEUP}) — {reason}")
            record_task_failure(state, key, reason)

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
                record_task_success(state)
                same_task_streak = 0
                last_failed_key = None
                in_diagnosis = False
                diagnosis_failures = 0

        else:
            # Normal failure
            record_task_failure(state, key, reason)

            if key == last_failed_key:
                same_task_streak += 1
            else:
                same_task_streak = 1
                last_failed_key = key

            activity.log(
                f"Failure streak: {same_task_streak} same-task, "
                f"{state.get('consecutive_failures', 0)} consecutive (persistent)."
            )

            emit(e_path, ev.RETRY, key=key, streak=same_task_streak,
                 consecutive=state.get("consecutive_failures", 0))

            if state.get("consecutive_failures", 0) >= _CONSECUTIVE_THRESHOLD:
                activity.log(
                    f"Too many consecutive failures ({state['consecutive_failures']}) — "
                    "recording finding and resetting."
                )
                add_finding(
                    title=f"Repeated failures: {state['consecutive_failures']} consecutive",
                    description=(
                        f"Multiple consecutive failures across different tasks.\n"
                        f"Last failure: {reason}"
                    ),
                    severity="high",
                    path=f_path,
                )
                record_task_success(state)
                same_task_streak = 0
                last_failed_key = None

        # ── state persistence ─────────────────────────────────────────────────
        activity.log("Saving state...")
        set_phase(state, RunState.IDLE)
        heartbeat(state)
        refresh_control_flags(state, s_path)
        save_state(state, s_path)
        _write_state_md(
            md_path, task, result.stdout, result.stderr, repo_after,
            outcome != FAILURE, reason, evidence,
        )
        activity.log(f"State saved. Tasks completed: {state['tasks_completed']}")

        activity.log("Waiting 10s before next task...")
        if cancel_token.wait(10):
            activity.log("Stop requested during inter-task sleep — exiting.")
            emit(e_path, ev.LOOP_STOPPED, reason="stop_during_inter_task_sleep")
            state = load_state(s_path)
            mark_stopped(state)
            set_phase(state, RunState.STOPPED)
            save_state(state, s_path)
            break
