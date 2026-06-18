# Alpha Release Checklist

Run through this checklist before each alpha release and after significant changes.

---

## Installation

- [ ] `pip install romyq` succeeds on a fresh virtual environment
- [ ] `romyq --version` prints the correct version
- [ ] `python -m romyq --version` works (package entrypoint)
- [ ] `romyq --help` lists all commands without error
- [ ] Installing from the built wheel works: `pip install dist/romyq-*.whl`

---

## Doctor

- [ ] `romyq doctor` passes on a correctly configured machine
- [ ] `romyq doctor` fails clearly when `DEEPSEEK_API_KEY` is missing
- [ ] `romyq doctor` fails clearly when `claude` CLI is not in PATH
- [ ] `romyq doctor` fails clearly when `mission.md` is absent
- [ ] Each failed check shows an actionable fix hint

---

## New Project Onboarding

- [ ] `romyq init` creates `mission.md`, `.romyq/`, and a git repo in the current directory
- [ ] `romyq init myproject` creates everything inside `myproject/` (not the parent dir)
- [ ] `romyq doctor` passes immediately after `romyq init` with no extra steps
- [ ] Editing `mission.md` and running `romyq run` starts the loop
- [ ] `romyq status` shows state after the first task completes
- [ ] `romyq logs` shows history after the first task completes

---

## Existing Project Onboarding

- [ ] `romyq attach` on a clean existing repo creates `.romyq/` and `mission.md`
- [ ] `romyq attach` adds `.romyq/` to `.gitignore` without breaking the repo
- [ ] `romyq info` shows correct language, frameworks, and test suite
- [ ] `romyq run` starts the loop after attaching (current directory by default)
- [ ] Running `romyq run` without prior attach still works (bootstrap handles it)

---

## Safety

- [ ] Running on a **dirty repo** (uncommitted changes) shows a warning per task
- [ ] A validation failure on a dirty repo does **not** restore (destroy) user files
- [ ] Running on a **clean repo** restores the working tree on validation failure
- [ ] Stopping Romyq with Ctrl-C leaves the repo in a valid git state
- [ ] After an interrupted run, `romyq status` still reads state correctly
- [ ] `romyq run` on a repo with `.romyq/` already in `.gitignore` does not make spurious commits

---

## Steering Notes

- [ ] `romyq note "message"` creates or appends to `.romyq/notes.md`
- [ ] `romyq note ""` (empty) exits with a clear error
- [ ] Notes are visible in `romyq info` output
- [ ] Notes persist across `romyq run` restarts
- [ ] Notes appear in DeepSeek prompt on next task (visible in activity log)

---

## Timeout and Reliability

- [ ] `ROMYQ_CLAUDE_TIMEOUT=60 romyq run` enforces a 60-second timeout
- [ ] On timeout, the Claude subprocess is terminated and the task is failed cleanly
- [ ] A corrupted `state.json` prints a warning and resets to defaults
- [ ] After a rate-limit sleep, the loop resumes automatically

---

## Documentation

- [ ] README `Quick Start` matches current `romyq init` / `romyq run` flow
- [ ] All commands listed in README match `romyq --help` output
- [ ] `romyq note` is documented in the Commands section
- [ ] Configuration table is accurate (env var names and defaults)
- [ ] State file locations in README match actual `.romyq/` layout
- [ ] `RELEASE.md` steps produce a working release

---

## Version Consistency

- [ ] `romyq --version` matches the `version` field in `pyproject.toml`
- [ ] `romyq version` does not show `0.0.0+unknown`
- [ ] `python -m romyq --version` reports the same version as `romyq --version`
- [ ] After `pip install dist/*.whl --force-reinstall`, `romyq --version` reports the wheel version
- [ ] For editable installs: after bumping `pyproject.toml` version, re-run `pip install -e .` and confirm `romyq version` reflects the new version
- [ ] `romyq version` shows `editable` for dev installs and `wheel or sdist` for release installs

---

## Release Verification

- [ ] `python -m build` produces `dist/*.whl` and `dist/*.tar.gz` without errors
- [ ] Version in `pyproject.toml` matches the intended release tag
- [ ] `git status` is clean before tagging
- [ ] `romyq --version` and `romyq version` both report the release version (install wheel to verify)
- [ ] Pushing `v*` tag triggers the GitHub Actions release workflow
- [ ] All 4 platform binaries appear in the GitHub Release assets
- [ ] PyPI publish step completes (check Actions logs)
- [ ] `pip install romyq==<version>` installs the new version from PyPI
- [ ] `romyq version` after PyPI install shows `wheel or sdist` (not `editable`)
