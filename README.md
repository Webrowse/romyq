# Romyq

Autonomous AI software project manager.

Give Romyq a software goal.
It plans, codes, commits, audits, and keeps improving until you stop it.

> Run `romyq ui` to launch the live dashboard while `romyq run` is active.

---

## Install

```bash
brew install webrowse/street/romyq   # macOS / Linux (Homebrew)
pip install romyq                    # any platform with Python 3.10+
```

---

## 60-Second Quick Start

```bash
mkdir my-project
cd my-project
git init

romyq init
# The wizard asks for your mission, complexity profile,
# and DeepSeek API key, then writes .env and mission.md.

romyq doctor
romyq run
```

Attaching to an existing repository instead:

```bash
cd my-existing-project
romyq attach                             # creates .romyq/ and a mission.md template
echo "DEEPSEEK_API_KEY=sk-..." >> .env   # set your key
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
| `romyq init` | Create a new managed workspace (runs interactive wizard) |
| `romyq init --no-wizard` | Non-interactive init (legacy behavior) |
| `romyq init --no-vcs` | Init without running `git init` |
| `romyq doctor` | Validate environment and configuration |

**Running**

| Command | Description |
|---|---|
| `romyq run` | Start the autonomous development loop |
| `romyq run --approval` | Prompt for approval before each Claude execution |
| `romyq note "message"` | Inject a steering note into the next task |
| `romyq steer "instruction"` | Send a live operator instruction to the planner |
| `romyq rules` | List active project rules and promotion suggestions |
| `romyq rules add "TEXT"` | Add a project rule (e.g. "Never use SQLite") |
| `romyq rules remove "TEXT"` | Remove a project rule by text or ID |
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

**Lifecycle**

| Command | Description |
|---|---|
| `romyq roadmap` | Show the lifecycle roadmap with phase progress |
| `romyq lifecycle` | Show or manage the software lifecycle |
| `romyq phase` | Show the current lifecycle phase and tasks |
| `romyq profile` | Show or set the project complexity profile |
| `romyq recommendation` | Show the current Continue / Pause / Review / Stop recommendation |
| `romyq dashboard` | Show the lifecycle-first project dashboard |
| `romyq architecture` | Show the lifecycle architecture flow diagram |
| `romyq shell` | Launch the live operator shell alongside a running loop |

**Governance & Visibility**

| Command | Description |
|---|---|
| `romyq readiness` | Mission readiness score: Core Functionality, Testing, Security, Operations |
| `romyq capabilities` | Show the project capability model (what's missing/partial/complete) |
| `romyq capabilities set <name> <status>` | Manually set a capability: `missing \| partial \| complete` |
| `romyq capabilities infer` | Infer capabilities from task history |
| `romyq project-timeline [--last N]` | Project evolution timeline ("Added Authentication", not "Task #17") |
| `romyq constitution` | Generate `.romyq/project.md` — single document view of the whole project |

**Intelligence & Diagnostics**

| Command | Description |
|---|---|
| `romyq learn` | Generate or refresh `.romyq/context.md` from static analysis |
| `romyq planning [--json]` | Planning diagnostics: memory signals, knowledge signals, loop detection |
| `romyq memory [--json]` | Execution memory: failure rates, retry patterns, mission outcomes |
| `romyq knowledge [--json]` | Knowledge base: synthesized lessons and extracted patterns |
| `romyq patterns [--json]` | Extracted failure and success patterns from the knowledge base |
| `romyq plan [--json]` | Show the current mission task plan with status |
| `romyq decisions [--json]` | Show the governance decision log |
| `romyq explain` | Full diagnostic picture: state, failures, recovery guidance |

**Meta**

| Command | Description |
|---|---|
| `romyq version` | Show version, install type, and Python version |
| `romyq ui` | Launch the Textual TUI dashboard (`pip install 'romyq[ui]'`) |

---

## Configuration

Romyq reads a `.env` file from your project directory (`romyq init` writes it for you):

```
DEEPSEEK_API_KEY=sk-...      # required — planning provider
ROMYQ_CLAUDE_TIMEOUT=1800    # optional — per-task Claude timeout in seconds
```

The planner defaults to DeepSeek but any OpenAI-compatible endpoint works:

```
ROMYQ_PLANNER_BASE_URL=https://api.deepseek.com   # optional
ROMYQ_PLANNER_MODEL=deepseek-chat                 # optional
ROMYQ_PLANNER_TIMEOUT=600                         # optional, seconds per request
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
