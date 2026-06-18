# Romyq

Autonomous AI software project manager.

Give Romyq a software goal.
It plans, codes, commits, audits, and keeps improving until you stop it.

> Screenshot coming soon — `romyq ui` (Textual TUI)

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

| Command | Description |
|---|---|
| `romyq attach` | Initialize Romyq in the current directory |
| `romyq doctor` | Validate environment and configuration |
| `romyq run` | Start the autonomous loop |
| `romyq ui` | Launch the Textual TUI dashboard |
| `romyq status` | Show current mission and task state |

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

## Changelog

See [CHANGELOG.md](./CHANGELOG.md).

---

## License

MIT
