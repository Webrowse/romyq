# Changelog

## 0.5.0

**Execution memory and failure-aware planning — Romyq now remembers its past mistakes.**

**Execution Memory (`romyq/memory.py` + `.romyq/memory.json`):**
- Add: Per-task execution memory persisted in `.romyq/memory.json`. Each task execution records: task fingerprint, normalized text, mission fingerprint, validator outcome, evidence (capped at 5 lines), failure reason, retry count, completion status, and ISO timestamp.
- Add: Bounded growth — defaults to 2 000 entries, configurable via `ROMYQ_MAX_MEMORY`. Oldest entries pruned automatically on `record()`.
- Add: Mission-level outcome tracking. `update_mission()` accumulates per-mission totals (tasks total, completed, blocked) keyed by mission fingerprint; visible in `romyq memory`.
- Add: `record()`, `entries_for()`, `entries_similar_to()`, `recent_failures()`, `most_failed()`, `prior_outcomes_text()`, `overall_success_rate()`, `retry_rate()`, `avg_attempts_per_task()`, `recent_fingerprints()`, `mission_summary()`, `all_missions()`.
- All writes are atomic (tmp + fsync + os.replace). Corrupted `memory.json` is silently reset to an empty structure.

**Task Fingerprinting (`romyq/fingerprint.py`):**
- Add: `normalize(text)` — lowercases, collapses whitespace, strips non-semantic punctuation, preserves `/` and `-` for route paths and hyphenated identifiers.
- Add: `fingerprint(text)` — 12-character SHA-1 of normalized text. Deterministic; case-insensitive; whitespace- and punctuation-insensitive.
- Add: `similarity(a, b)` — Jaccard similarity (0.0–1.0) on meaningful word tokens (filler words removed). Scores ≥ 0.4 indicate related tasks.
- Add: `is_similar(a, b, threshold=0.4)` — shortcut combining exact fingerprint match and Jaccard check.
- Replace: `loop.py`'s `_task_key()` now uses `fingerprint.fingerprint()` for stable, normalized task identity. Old MD5-based keys expire on restart (no data migration needed — keys only matter for the current session).

**Planner Loop Detection (`romyq/loop_detector.py`):**
- Add: `LoopPattern(pattern_type, fingerprints, count, description)` NamedTuple.
- Add: `detect(fps, straight_threshold=3, oscillation_min=4)` — detects straight loops (same FP N+ times in a row) and A-B oscillations (two FPs strictly alternating over M+ iterations).
- Add: `describe(patterns)` — compact multi-line summary for CLI display.
- Integrated into `romyq health` via `detect_stuck_conditions(memory_path=...)` and into `romyq explain` "Planner Loop Detection" section.

**Failure-Aware Planning:**
- Add: `planning.build_memory_context(memory_path)` — builds a "Top Failed Tasks" prompt section from execution memory for injection into DeepSeek planning calls. Tasks that have failed repeatedly are listed with their last failure reason so the planner avoids proposing them again.
- Update: `build_planning_context()` accepts `memory_path` parameter and injects memory context between repository context and recent-failures sections.
- Update: `manager.generate_task()` passes `memory_path` to `build_planning_context()`.
- Update: After task generation in `loop.py`, prior outcomes for the generated task are looked up in memory. If found, the failure context is appended to the task prompt sent to Claude so the executor is also aware of prior failures.
- Update: After each task execution, `memory.record()` and `memory.update_mission()` are called. Wrapped in `try/except` so memory writes never crash the loop.

**New CLI Commands:**
- Add: `romyq planning [--json]` — shows current planning context (repository memory summary, injected failure context, blocked task state), planner loop detection results, and repeated-task warnings.
- Add: `romyq memory [--json]` — shows execution memory analysis: total entries, success rate, retry rate, average attempts per task, top failed tasks (with FP and last reason), planner loop detection, and mission outcome summary.

**Updated CLI Commands:**
- Update: `romyq explain` — adds "Planner Loop Detection" section after Recovery Guidance.
- Update: `romyq health` — passes `memory_path` to `detect_stuck_conditions()` so loop patterns are included in health warnings.
- Update: `romyq stats [--json]` — passes `memory_path` to `compute()`; displays memory-derived fields (retry rate, avg attempts/task, blocked-task rate, planner loop count) when non-zero.
- Update: `romyq/store.py` — adds `memory_path(workspace)` returning `.romyq/memory.json` path.

**Metrics Expansion (`romyq/metrics.py`):**
- Add: `LoopMetrics.task_retry_rate` — fraction of unique task FPs retried ≥1 time (from memory).
- Add: `LoopMetrics.avg_attempts_per_task` — average execution attempts per unique task FP (from memory).
- Add: `LoopMetrics.blocked_task_rate` — blocked events / history entries (from events + history).
- Add: `LoopMetrics.planner_loop_count` — count of detected loop patterns in recent memory (from loop_detector).
- All new fields have defaults (0.0/0) and are populated only when `memory_path` is provided; backward compatible.

**Testing:**
- Add: `tests/test_fingerprint.py` — 37 tests for normalize, fingerprint, similarity, is_similar, _tokens.
- Add: `tests/test_memory.py` — 51 tests for all memory module functions including persistence, bounded growth, pruning, atomicity, mission tracking, and query functions.
- Add: `tests/test_loop_detector.py` — 27 tests for straight loop and oscillation detection, edge cases, and describe().
- Add: `tests/test_memory_cli.py` — 24 tests for `romyq planning` and `romyq memory` CLI commands (human and JSON output).
- Tests: 359 → 511 (+152).

## 0.4.0

**Long-running autonomous execution — safe for multi-day unattended operation:**

- Add: `romyq learn` — generate or refresh `.romyq/context.md` from static analysis (language, frameworks, build commands, CI workflows, coding conventions, git age). No AI required; deterministic and safe to regenerate at any time. Context is automatically generated on first `romyq run` and included in every DeepSeek planning prompt.
- Add: `romyq stats [--json]` — long-run operational statistics: tasks completed, tasks blocked, validator pass/fail counts, pass rate, cancellation count, rate-limit event count, total events, and runtime hours (derived from `loop_started`/`loop_stopped` event pairs so it survives restart).
- Add: `romyq timeline [--last N] [--json]` — human-readable event timeline with labelled event types and inline detail (reason, task preview, key).
- Add: `romyq explain` now shows a "Recovery Guidance" section with severity (`ok`/`warning`/`error`), a one-line situation description, and a concrete recommendation derived from the current phase, heartbeat age, failure streak, and stop/pause flags.
- Add: `romyq health` now shows a "Warnings" section listing stuck conditions: task retried above ceiling, consecutive failure streak, validator evidence unchanged across N failures, stale heartbeat in an active phase, and rate-limit storm detection.
- Add: `romyq/context.py` — repository memory module. `generate()` performs static analysis; `write()` atomically writes `.romyq/context.md`; `load()` reads it. Context includes project type, frameworks, build commands, test runner, CI/CD systems, coding conventions (editorconfig, ruff, black, mypy, ESLint, Prettier, husky), and first-commit date.
- Add: `romyq/recovery.py` — `RecoveryState(situation, recommendation, severity)` NamedTuple. `analyze_recovery_state()` handles all phases plus: stop-requested mismatch, pause-flag mismatch, blocked task, stale heartbeat (>30 min in active phase), and consecutive-failure streak (≥5).
- Add: `romyq/metrics.py` — `LoopMetrics` NamedTuple + `compute(state, history_path, events_path)`. Computes all statistics from existing files; no new persistent state.
- Add: `romyq/health_checks.py` — `detect_stuck_conditions(state, history_path, events_path, heartbeat_age_s)` returns a list of warning strings. Detects: blocked task (attempts ≥ ceiling), consecutive failure streak (≥5), validator evidence unchanged across last 3 failures, stale heartbeat in active phase (>30 min), and rate-limit storm (≥3 in last 50 events).
- Add: `romyq/planning.py` — `build_planning_context()` assembles a prompt section from repository memory, last 10 failures, blocked-task warning (if any), last validator evidence, and unresolved findings. Injected into every DeepSeek `generate_task()` call so the planner avoids repeated failed approaches.
- Add: `romyq/loop.py` auto-generates `.romyq/context.md` at startup when absent, or when `ROMYQ_REFRESH_CONTEXT=1` is set.
- Add: `romyq/store.py` exports `context_path(workspace)` for `.romyq/context.md`.
- Add: `manager.generate_task()` accepts optional `state_dict` parameter; when provided, builds and injects the full planning context into the DeepSeek prompt.

**Testing:**

- Add: `tests/test_context.py` — 20 tests for context generation, CI/workflow detection, convention detection, atomic write, and load.
- Add: `tests/test_recovery.py` — 20 tests for `RecoveryState` and `analyze_recovery_state()` across all phases, special cases, and edge conditions.
- Add: `tests/test_metrics.py` — 17 tests for `LoopMetrics`, `compute()`, history counting, event counting, and runtime hour calculation.
- Add: `tests/test_stuck_detection.py` — 20 tests for `detect_stuck_conditions()` covering all five detection categories.
- Add: `tests/test_planning_context.py` — 18 tests for `build_planning_context()` covering all injected sections and edge cases.
- Add: `tests/test_timeline.py` — 12 tests for `romyq timeline` and `romyq stats` CLI commands.
- Add: `tests/test_long_running.py` — 7-day reliability simulation: 7-session restart resilience, progressive failure accumulation, rate-limit storm detection, crash recovery analysis, context persistence, and stats accumulation.
- Tests: 244 → 359 (+115).

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
