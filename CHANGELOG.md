# Changelog

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
