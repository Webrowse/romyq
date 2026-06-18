# Changelog

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
