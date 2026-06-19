# Changelog

## 0.3.0

**Durability and recovery hardening:**

- Fix: All JSON write paths (`state.json`, `findings.json`, `history.json`) now call `f.flush()` + `os.fsync()` inside the `NamedTemporaryFile` context before `os.replace()`. Without fsync, a power failure between file-close and `os.replace()` could leave an empty or partial temp file, causing the loop to silently reset all persistent counters on restart.
- Fix: `_write_state_md()` is now atomic (tmp + fsync + os.replace). Previously a crash during write left a partial Markdown file.
- Fix: `events.prune()` uses atomic tmp + fsync + os.replace when rewriting the log.
- Fix: Workspace is now rolled back after `ClaudeCancelledError`. Previously, stopping the loop while Claude was editing files left the working tree in an unknown dirty state; the next run would immediately fail validation. `rollback()` is now called in the cancellation handler before exiting.
- Fix: Inter-task sleep now uses `cancel_token.wait(10)` instead of `time.sleep(10)`. A stop request during the 10-second gap is now honoured within POLL_INTERVAL (5 s) rather than up to 10 s later.
- Fix: SIGTERM and SIGINT now set `stop_requested` in `state.json` so the cancel token fires on the next poll, Claude is terminated, the workspace is rolled back, and a `LOOP_STOPPED` event is written before exit.
- Fix: Removed dead code in the normal-failure path (`persistent_consec = record_task_failure(...) or ...`; `record_task_failure` returns None and the variable was never used).

**New observability features:**

- Add: `romyq explain` — single command showing the full diagnostic picture: loop state, phase, heartbeat, current task (full text), task key, attempt count vs ceiling (with BLOCKED label), consecutive failures, last failure reason, last failure timestamp, and all validator evidence lines.
- Add: `romyq status --json` — machine-readable JSON output of the complete `state.json` for scripting, monitoring, and CI integration.
- Add: `events.prune(path, max_entries)` — removes oldest events to cap the log at `max_entries` lines. Called automatically at loop startup with `ROMYQ_MAX_EVENTS` (default 10 000).
- Add: `validator.rollback(workspace, pre_dirty, pre_dirty_paths)` — public function wrapping the selective/full restore logic, usable from any code that exits before reaching the validator.

**Testing:**

- Add: `tests/test_atomic_writes.py` — 20 tests verifying fsync + os.replace across state, findings, history, and events.prune().
- Add: `tests/test_rollback.py` — 11 tests for the public `rollback()` function including pre-dirty preservation and nested directories.
- Add: `tests/test_explain_cmd.py` — 11 tests for `romyq explain` and `romyq status --json`.
- Add: `tests/test_smoke.py` — real-subprocess tests for `_terminate()`, timeout, and CancellationToken cancellation; optional claude-binary tests guarded with `@pytest.mark.smoke`.
- Tests: 193 → 244 (+51).

## 0.2.0

**Reliability hardening — safe to run unattended for 8–12 hours:**

- Add: `CancellationToken` — file-polling stop/pause token with 5s interval; stop latency is now ≤5s (was up to 30s)
- Add: Claude mid-task cancellation — `runner.run()` polls the token every 5s and terminates Claude via SIGTERM, raising `ClaudeCancelledError`
- Add: Persistent failure tracking — `current_task_key`, `current_task_attempts`, `last_failure_reason`, `last_failure_timestamp`, `consecutive_failures`, `max_task_attempts` all written to `state.json` and survive restarts
- Add: Blocked-task detection — tasks that exceed `max_task_attempts` (default 3) are skipped with a finding instead of retried indefinitely
- Add: `RunState` enum with documented transitions (`IDLE → PLANNING → EXECUTING → VALIDATING → IDLE`); `STOPPING`/`STOPPED` reachable from any state as an emergency exit
- Add: `set_phase()` — validates transitions, warns on invalid, updates heartbeat; `phase` field visible in `romyq status` and `romyq health`
- Add: `ValidationResult` NamedTuple — `(outcome, reason, evidence[])` where evidence includes exit code, git diff lines, and stdout tail for postmortem debugging
- Add: Append-only NDJSON event log at `.romyq/events.log`; `romyq events [--last N]` command; "Recent Events" section in `romyq report`
- Add: `refresh_control_flags()` merges `paused`/`stop_requested` from disk before every `save_state()` call — CLI control commands issued during long Claude executions are no longer silently discarded
- Fix: validator three-way outcome (`SUCCESS` / `FAILURE` / `NO_ACTION_REQUIRED`) — already-complete tasks advance without incrementing failure streaks or creating findings
- Fix: `romyq version` now shows `executable` (absolute path) and `venv` (active virtualenv); warns when not running inside a venv
- Fix: RELEASE.md and ALPHA_CHECKLIST.md use isolated venv paths (`$TDIR/bin/romyq`) to prevent PATH-shadowing false positives during release verification
- Fix: state write-after-read race — `refresh_control_flags()` prevents loop saves from overwriting CLI pause/stop signals
- Fix: dirty repository state compounding — `_selective_restore()` cleans only Claude's additions on failure, leaving pre-existing uncommitted changes intact
- Fix: undefined `key` variable on rate-limit retry path
- Fix: generic phrase rate-limit false positives — only the specific Claude session-limit message triggers rate-limit handling
- Tests: 91 → 193 (+102); four new test modules: `test_cancellation`, `test_events`, `test_failure_tracking`, `test_runstate`; overnight simulation scenarios in `test_simulation`

**Observability and loop control (included from 0.1.2–0.1.3 unreleased):**

- Add: `romyq ui` — live Textual dashboard (`pip install 'romyq[ui]'`)
- Add: `romyq health` — operational health snapshot
- Add: `romyq report` — full human-readable project summary
- Add: `romyq pause` / `romyq resume` / `romyq stop` — loop control via state flags
- Add: Claude rate-limit detection — parses `resets HH:MMam (TZ)`, sleeps until reset + 5 min buffer, retries same task
- Add: `.github/ISSUE_TEMPLATE/` — bug report and feature request forms

## 0.1.1

- Fix: `romyq init` now creates everything inside the workspace directory
- Fix: `romyq attach` now creates `mission.md` inside the workspace directory when a path is specified
- Fix: version fallback changed from hardcoded `"0.1.0"` to `"0.0.0+unknown"`
- Add: `romyq version` subcommand — shows version, install type, and Python version
- Add: regression tests for the init flow (`tests/test_init_flow.py`)

## 0.1.0 — Initial alpha

First public release.

- Autonomous development loop: DeepSeek plans tasks, Claude Code implements them
- `romyq attach` — attach to any existing git repository
- `romyq run` — start the autonomous loop (current directory by default)
- `romyq doctor` — validate environment before running
- `romyq status` / `romyq logs` — inspect runtime state
- `romyq info` — detect language, frameworks, test suite, and build commands
- `romyq note` — inject steering notes into task generation
- `.romyq/` state directory — self-contained per repository
- Repeated-failure detection with automatic diagnosis mode
- Claude execution timeout (configurable via `ROMYQ_CLAUDE_TIMEOUT`)
- Pre-existing uncommitted changes are never destroyed on validation failure
- Real-time Claude stdout streaming with `[Claude]` prefix
