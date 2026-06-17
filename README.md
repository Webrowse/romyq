# Romyq

Autonomous AI software project manager.

Write a mission. Romyq builds it.

```
romyq init
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

```bash
# 1. Create a project directory
mkdir myproject && cd myproject

# 2. Add your DeepSeek API key
echo "DEEPSEEK_API_KEY=your-key-here" > .env

# 3. Initialize
romyq init

# 4. Describe what you want to build (free-form, any length)
echo "Build a CLI tool that converts Markdown to HTML." > mission.md

# 5. Run
romyq run
```

Romyq will start generating and implementing tasks in the `workspace/` directory.
To use an existing repository instead:

```bash
romyq run /path/to/existing/repo
```

## Commands

### `romyq init [workspace]`

Initializes a new project. Creates `mission.md` if it does not exist and
bootstraps the workspace as a git repository.

```bash
romyq init                  # uses workspace/ subdirectory
romyq init /path/to/repo    # uses an existing directory
```

### `romyq run [workspace]`

Starts the autonomous development loop. Reads `mission.md` from the current
directory. Workspace defaults to `workspace/` or `$ROMYQ_WORKSPACE`.

```bash
romyq run
romyq run /path/to/repo
ROMYQ_WORKSPACE=/path/to/repo romyq run
```

### `romyq status`

Shows the current run state: tasks completed, last commit, heartbeat.

```bash
romyq status
```

### `romyq logs [--last N]`

Shows recent task history. Defaults to the last 10 entries.

```bash
romyq logs
romyq logs --last 25
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
| `ROMYQ_WORKSPACE` | `workspace/` | Workspace directory path. |

Place these in a `.env` file in the directory where you run `romyq`.

## State files

Romyq writes the following files to the current directory:

| File | Purpose |
|---|---|
| `mission.md` | Your mission (you write this) |
| `state.json` | Current run state |
| `state.md` | Human-readable summary of the last task |
| `task_history.json` | Full task history |
| `audit_report.json` | Audit findings (created during audit cycles) |

## License

MIT
