# Romyq

Autonomous AI software project manager.

Give Romyq a software goal.
It plans, codes, commits, audits, and keeps improving until you stop it.

> Run `romyq ui` to launch the live dashboard while `romyq run` is active.

---

## Install

```bash
pip install romyq
```

---

## 60-Second Quick Start

```bash
mkdir my-project
cd my-project
git init

cp .env.example .env
# Open .env and add your DEEPSEEK_API_KEY

romyq attach
# Edit mission.md — describe what you want built

romyq doctor
romyq run
```

That's it. Romyq takes over from here.

---

## What Happens Next

- Romyq reads `mission.md`
- DeepSeek generates a task plan
- Claude Code implements each task
- Every successful task creates a git commit
- Romyq audits progress and keeps improving the project

---

## Commands

**Setup**

| Command | Description |
|---|---|
| `romyq attach` | Attach Romyq to an existing git repository |
| `romyq init` | Create a new managed workspace in the current directory |
| `romyq doctor` | Validate environment and configuration |

**Running**

| Command | Description |
|---|---|
| `romyq run` | Start the autonomous development loop |
| `romyq note "message"` | Inject a steering note into the next task |
| `romyq pause` | Pause the loop after the current task finishes |
| `romyq resume` | Resume a paused loop |
| `romyq stop` | Request graceful shutdown after the current task |

**Observability**

| Command | Description |
|---|---|
| `romyq health` | High-level health summary: tasks, failures, findings, heartbeat |
| `romyq report` | Full project report: mission, progress, commits, notes, findings |
| `romyq status` | Raw state: current task, last commit, heartbeat timestamp |
| `romyq logs` | Per-task history with success/failure and validation reason |
| `romyq info` | Detected language, frameworks, test suite, and build commands |
| `romyq stats [--json]` | Long-run operational statistics: tasks, validator rates, runtime |
| `romyq timeline [--last N] [--json]` | Human-readable event timeline |

**Intelligence & Diagnostics**

| Command | Description |
|---|---|
| `romyq learn` | Generate or refresh `.romyq/context.md` from static analysis |
| `romyq planning [--json]` | Planning diagnostics: memory signals, knowledge signals, loop detection |
| `romyq memory [--json]` | Execution memory: failure rates, retry patterns, mission outcomes |
| `romyq knowledge [--json]` | Knowledge base: synthesized lessons and extracted patterns |
| `romyq patterns [--json]` | Extracted failure and success patterns from the knowledge base |
| `romyq explain` | Full diagnostic picture: state, failures, recovery guidance |

**Meta**

| Command | Description |
|---|---|
| `romyq version` | Show version, install type, and Python version |
| `romyq ui` | Launch the Textual TUI dashboard (coming soon) |

---

## Configuration

Copy the example file and fill in your keys:

```bash
cp .env.example .env
```

`.env.example`:

```
DEEPSEEK_API_KEY=
ROMYQ_CLAUDE_TIMEOUT=1800
```

---

## Advanced Usage

Run against an existing repository:

```bash
romyq attach /path/to/repo
romyq run /path/to/repo
```

Set workspace via environment variable:

```bash
ROMYQ_WORKSPACE=/path/to/repo romyq run
```

---

## Requirements

- Python 3.10+
- Claude Code installed and authenticated
- DeepSeek API key
- Git initialized in your project directory

---

## Dashboard

`romyq ui` opens a live Textual dashboard that reads state files while `romyq run` is active in another terminal.

```
┌─ romyq  /path/to/project  ● running  tasks:12  hb:30s  commit:abc1234 ─┐
│                                                                          │
│  Current Task                 │  Claude Output                          │
│  ─────────────────────────    │  ──────────────────────────────────     │
│  Implement JWT authentication │  Created auth/jwt.py                    │
│  for the admin API. Add       │  Added TokenMiddleware to app.py        │
│  middleware to validate all   │  All 24 tests passing                   │
│  protected routes.            │  Committed: feat: add JWT auth          │
│  ─────────────────────────    │                                         │
│  Task History                 │  ──────────────────────────────────     │
│  ─────────────────────────    │  Findings          │  Notes             │
│  ✓ 15:42 impl  Add OAuth...   │  ─────────────────────────────────     │
│  ✗ 15:40 impl  Add tests...   │  [HIGH]  Repeated failure: progress    │
│  ✓ 15:38 audi  Fix vulns...   │  [MEDI]  Missing input validation      │
│  ✓ 15:35 impl  Add models...  │                                         │
│                               │                                         │
└──────────────────────────────────────────────────────────────────────────┘
│  q quit  r refresh                                                       │
```

**Install the dashboard:**

```bash
pip install 'romyq[ui]'
```

**Launch alongside a running loop:**

```bash
# Terminal 1
romyq run

# Terminal 2
romyq ui
```

The dashboard polls state files every 2 seconds. No changes to the running loop are required.

---

## Rate Limit Handling

When Claude hits a session or usage limit, Romyq detects it automatically instead of treating it as a task failure:

- Parses the reset time from Claude's output (e.g. `resets 5:50am (Asia/Calcutta)`)
- Logs the reset time and timezone
- Sets `status: rate_limited` in state (visible in `romyq ui` and `romyq status`)
- Sleeps until the reset time plus a 5-minute safety buffer
- Retries the same task — no new DeepSeek call is wasted
- Falls back to a 30-minute sleep if the reset time cannot be parsed

The loop can be stopped early during a rate-limit sleep with `romyq stop`.

---

## Loop Control

Run these from any terminal while `romyq run` is active in another:

```bash
romyq pause    # idle after current task (loop keeps running)
romyq resume   # resume a paused loop
romyq stop     # exit gracefully after current task (or wake from rate-limit sleep)
```

These commands write flags to `.romyq/state.json`. The loop reads them between tasks.

---

## Changelog

See [CHANGELOG.md](./CHANGELOG.md).

---

## License

MIT
