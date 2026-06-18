# Romyq

Autonomous AI software project manager.

Write a mission. Romyq builds it.

```
cd myproject
romyq attach
romyq run
```

## How it works

1. You write a free-form mission in `mission.md`
2. Romyq reads the mission and generates the next coding task (via DeepSeek)
3. Claude Code implements the task and commits the result
4. Romyq validates the commit, records the result, and repeats
5. The loop continues until the mission is complete

The repository is the source of truth. Every completed task produces a git commit.

## Requirements

- Python 3.11+
- [Claude Code](https://claude.ai/code) CLI installed and authenticated (`claude`)
- [DeepSeek](https://platform.deepseek.com/) API key
- git

## Installation

```bash
pip install romyq
```

## Quick start

### Existing repository

```bash
cd myproject
echo "DEEPSEEK_API_KEY=your-key-here" > .env
romyq attach                                    # set up .romyq/ and create mission.md
echo "Add a REST API for user management." > mission.md
romyq run                                       # start the loop
```

### New project from scratch

```bash
mkdir myproject && cd myproject
echo "DEEPSEEK_API_KEY=your-key-here" > .env
romyq init                                      # creates workspace/ subdirectory
echo "Build a CLI tool that converts Markdown to HTML." > mission.md
romyq run workspace                             # run on the workspace/ subdirectory
```

> **Safety:** Romyq will not restore (reset) the working tree if you have
> uncommitted changes when a task starts. Commit or stash any in-progress
> work before running for full safety guarantees.

## Commands

### `romyq attach [path]`

Attaches Romyq to an **existing** repository. Safe to run on any project —
never modifies application code, never creates commits, never initializes git.

```bash
cd myproject
romyq attach          # attaches to current directory
romyq attach /path/to/repo
```

What it does:
- Creates `{repo}/.romyq/` for state storage
- Adds `.romyq/` to the repo's `.gitignore`
- Creates `mission.md` in the current directory if absent

### `romyq info [path]`

Shows what Romyq detects about a repository before starting a run.

```bash
romyq info            # inspect current directory
romyq info /path/to/repo
```

Example output:
```
  Language:         python
  Frameworks:       FastAPI, SQLAlchemy
  Test suite:       pytest  (dirs: tests/  |  config: pytest.ini)
  Build:            make dev
                    make test
                    pytest
  Branch:           main

  Mission:          ✓  found
  Tasks:            0 completed  (status: running)
  State dir:        ✓  /path/to/repo/.romyq/
```

### `romyq note "message" [workspace]`

Appends a steering note for the AI manager. Notes are injected into every
task generation call as highest-priority guidance, so they take effect
immediately on the next task without restarting.

```bash
romyq note "Focus on admin UX."
romyq note "Ignore mobile support."
romyq note "Prioritize scanner stability."
```

Notes accumulate in `{workspace}/.romyq/notes.md` and persist across runs.
They do not overwrite `mission.md`. View current notes with `romyq info`.

### `romyq init [workspace]`

Initializes a **new** project. Creates `mission.md` if it does not exist and
bootstraps the workspace as a git repository.

```bash
romyq init                  # uses workspace/ subdirectory
romyq init /path/to/repo    # uses an existing directory
```

### `romyq run [workspace]`

Starts the autonomous development loop. Reads `mission.md` from the current
directory. Defaults to the current directory; override with a path or
`$ROMYQ_WORKSPACE`.

By default Romyq runs indefinitely. When the mission is considered complete it
logs the result and continues generating improvements (tests, docs, performance,
reliability, UX). Pass `--until-complete` to stop instead.

```bash
romyq run                        # current directory, continuous
romyq run --until-complete       # stop when mission is complete
romyq run /path/to/repo          # explicit path
romyq run workspace              # workspace/ subdirectory (romyq init default)
ROMYQ_WORKSPACE=/path/to/repo romyq run
```

### `romyq status [workspace]`

Shows the current run state: tasks completed, last commit, heartbeat.

```bash
romyq status
romyq status /path/to/repo
```

### `romyq logs [workspace] [--last N]`

Shows recent task history. Defaults to the last 10 entries.

```bash
romyq logs
romyq logs --last 25
romyq logs /path/to/repo --last 20
```

### `romyq doctor [workspace]`

Checks that all prerequisites are in place before running.

```bash
romyq doctor
romyq doctor /path/to/repo
```

Example output:

```
romyq doctor

  ✓  DEEPSEEK_API_KEY  (set)
  ✓  claude CLI  (/usr/local/bin/claude)
  ✓  git  (/usr/bin/git)
  ✓  mission.md  (found)
  ✓  workspace (workspace/)  (exists)
  ✓  workspace is a git repo  (yes)

All checks passed. Ready to run: romyq run
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DEEPSEEK_API_KEY` | — | Required. DeepSeek API key. |
| `ROMYQ_WORKSPACE` | current directory | Workspace directory path override. |
| `ROMYQ_CLAUDE_TIMEOUT` | `1800` | Claude subprocess timeout in seconds (default: 30 minutes). |

Place these in a `.env` file in the directory where you run `romyq`.

## State files

Romyq writes `mission.md` to the current directory and stores all runtime
state inside the managed repository under `.romyq/`:

| Location | Purpose |
|---|---|
| `mission.md` | Your mission — you write this, lives where you run romyq |
| `<workspace>/.romyq/state.json` | Current run state |
| `<workspace>/.romyq/state.md` | Human-readable summary of the last task |
| `<workspace>/.romyq/history.json` | Full task history |
| `<workspace>/.romyq/findings.json` | Audit findings |

`.romyq/` is automatically added to the workspace's `.gitignore` so it does
not pollute the repository's commit history.

Each managed repository has its own independent `.romyq/` directory, so
multiple repositories can be managed simultaneously with separate state.

### Working with state from any directory

`romyq status` and `romyq logs` accept a workspace argument (or read
`$ROMYQ_WORKSPACE`) so you can inspect state without being in the romyq
launch directory:

```bash
romyq status /path/to/repo
romyq logs /path/to/repo --last 20
ROMYQ_WORKSPACE=/path/to/repo romyq status
```

## License

MIT
