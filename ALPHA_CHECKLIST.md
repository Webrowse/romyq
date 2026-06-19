# Alpha Release Checklist

Run through this checklist before each alpha release and after significant changes.

---

## Installation

> Use absolute venv paths for verification — a global `romyq` may shadow the
> venv executable and silently produce a false positive.
>
> ```bash
> TDIR=/tmp/romyq-alpha-test
> python -m venv "$TDIR"
> "$TDIR/bin/pip" install romyq              # or dist/romyq-*.whl
> ```

- [ ] `$TDIR/bin/pip install romyq` succeeds on a fresh virtual environment
- [ ] `$TDIR/bin/romyq --version` prints the correct version
- [ ] `$TDIR/bin/romyq version` `executable` field points inside `$TDIR/bin/`
- [ ] `$TDIR/bin/pip show romyq` shows `Name: romyq` and the expected version
- [ ] `python -m romyq --version` works (package entrypoint from dev environment)
- [ ] `$TDIR/bin/romyq --help` lists all commands without error
- [ ] Installing from the built wheel works: `$TDIR/bin/pip install dist/romyq-*.whl`

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
- [ ] `romyq version` `executable` field matches `which romyq` (or the absolute venv path)
- [ ] After `$TDIR/bin/pip install dist/*.whl`, `$TDIR/bin/romyq --version` reports the wheel version
- [ ] After wheel install: `$TDIR/bin/romyq version` `executable` points inside `$TDIR/bin/`
- [ ] For editable installs: after bumping `pyproject.toml` version, re-run `pip install -e .` and confirm `romyq version` reflects the new version
- [ ] `romyq version` shows `editable` for dev installs and `wheel or sdist` for release installs
- [ ] `romyq version` shows a `venv` path (not `none`) when run inside an active venv

---

## Release Verification

> Always use isolated venv paths to avoid PATH shadowing by a global install.
>
> ```bash
> RELEASE_VER=<version>
> TDIR=/tmp/romyq-release-test
> python -m venv "$TDIR"
> "$TDIR/bin/pip" install "dist/romyq-${RELEASE_VER}-py3-none-any.whl"
> "$TDIR/bin/romyq" --version          # romyq $RELEASE_VER
> "$TDIR/bin/romyq" version            # install: wheel or sdist; executable in $TDIR/bin
> "$TDIR/bin/pip"   show romyq         # Name: romyq, Version: $RELEASE_VER
> "$TDIR/bin/romyq" doctor
> rm -rf "$TDIR"
> ```

- [ ] `python -m build` produces `dist/*.whl` and `dist/*.tar.gz` without errors
- [ ] Version in `pyproject.toml` matches the intended release tag
- [ ] `git status` is clean before tagging
- [ ] Local wheel verified in isolated venv (commands above): version, install type, executable, pip show all correct
- [ ] `$TDIR/bin/romyq version` `executable` field is inside `$TDIR/bin/` (not a global path)
- [ ] `$TDIR/bin/pip show romyq` shows `Name: romyq` and `Version: $RELEASE_VER`
- [ ] Pushing `v*` tag triggers the GitHub Actions release workflow
- [ ] All 4 platform binaries appear in the GitHub Release assets
- [ ] PyPI publish step completes (check Actions logs)
- [ ] `pip install romyq==<version>` (in isolated venv) installs the new version from PyPI
- [ ] `$TDIR/bin/romyq version` after PyPI install shows `wheel or sdist` (not `editable`)
