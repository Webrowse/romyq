# Changelog

## 0.1.3 (unreleased)

**Release-verification and reliability fixes:**

- Fix: validator now returns a three-way outcome (`SUCCESS`, `FAILURE`, `NO_ACTION_REQUIRED`) — already-complete tasks advance without incrementing failure streaks or creating findings, and audit finding extraction is skipped for `NO_ACTION_REQUIRED`
- Fix: `romyq version` now shows `executable` (absolute path of the running binary) and `venv` (active virtual environment path); warns when not running inside a venv
- Fix: RELEASE.md and ALPHA_CHECKLIST.md now use isolated venv paths (`$TDIR/bin/romyq`) for all release verification steps, preventing PATH-shadowing by a global install from producing silent false positives

**Production-readiness fixes (top 5 audit findings):**

- Fix: state write-after-read race condition — `refresh_control_flags()` re-reads `paused` and `stop_requested` from disk immediately before every `save_state()` call; CLI pause/stop/resume commands are no longer silently discarded during Claude execution
- Fix: validator false-failed already-complete tasks — the `COMPLETED` marker in Claude's stdout is now recognised as success when returncode is 0 and no new dirty files were left; eliminates the infinite retry loop on tasks the repository already satisfies
- Fix: dirty repository state compounding across failures — `_selective_restore()` cleans only Claude's additions on failure, leaving pre-existing uncommitted changes intact; successive failures no longer accumulate junk in the working tree
- Fix: undefined `key` variable on rate-limit retry path — `pending_task_key` is stored alongside `pending_task` so the failure-tracking block never references a stale or undefined key
- Fix: generic phrase rate-limit false positives — removed pattern matching on `"rate limit"`, `"usage limit"`, `"too many requests"`, etc.; only the specific Claude session-limit message triggers rate-limit handling, preventing infinite 30-minute sleeps on projects that implement their own rate limiters

**Earlier additions in this release:**

- Add: Claude rate-limit detection — parses `resets HH:MMam (TZ)` from output, sleeps until reset + 5 min buffer, retries same task
- Add: `ClaudeRateLimitError` with `reset_at`, `tz_name`, `reset_display` attributes
- Add: `romyq pause` / `romyq resume` / `romyq stop` — loop control via state flags
- Add: state fields `resume_at`, `provider`, `paused`, `stop_requested`
- Add: dashboard shows `RATE LIMITED — resumes in Xm` and `PAUSED` status badges
- Add: tests for rate-limit detection, reset-time parsing, pause/resume/stop commands

## 0.1.2 (unreleased)

- Add: `romyq ui` — live Textual dashboard (optional dep: `pip install 'romyq[ui]'`)
  - Current task panel
  - Task history table
  - Last Claude output (from state.md)
  - Findings and steering notes (tabbed)
  - Status bar: status, task count, heartbeat age, last commit
  - Polls state files every 2 seconds; no changes to the running loop
- Add: `romyq health` — operational health snapshot
- Add: `romyq report` — full human-readable project summary
- Add: `.github/ISSUE_TEMPLATE/` — bug report and feature request forms

## 0.1.1

- Fix: `romyq init` now creates everything (`.romyq/`, `mission.md`, git repo) inside the workspace directory, not split between the workspace and its parent
- Fix: `romyq attach` now creates `mission.md` inside the workspace directory when a path is specified
- Fix: version fallback changed from hardcoded `"0.1.0"` to `"0.0.0+unknown"` so misconfigured installs are clearly visible
- Add: `romyq version` subcommand — shows version, install type (editable vs wheel), and Python version
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
