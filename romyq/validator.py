from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import NamedTuple

# ── validation outcomes ───────────────────────────────────────────────────────
# Three-state result: callers must check identity, not truthiness.
SUCCESS = "success"            # Claude committed work; repo is clean
FAILURE = "failure"            # something went wrong; workspace restored
NO_ACTION_REQUIRED = "no_action_required"  # Claude confirmed task already done

# Claude's prompt instructs it to print COMPLETED when it finishes a task.
_COMPLETED_RE = re.compile(r"\bCOMPLETED\b")

# Maximum stdout characters included in evidence (avoids giant log entries).
_EVIDENCE_STDOUT_LIMIT = 2000


class ValidationResult(NamedTuple):
    """Structured outcome from a validate() call.

    outcome  — one of SUCCESS / FAILURE / NO_ACTION_REQUIRED
    reason   — human-readable one-liner
    evidence — list of strings providing supporting detail (git diff lines,
               stdout tail, exit code) that is shown to Claude on retry and
               persisted in state.json["last_validation_evidence"]
    """

    outcome: str
    reason: str
    evidence: list[str]


# ── restore helpers ───────────────────────────────────────────────────────────

def _restore(workspace: str) -> None:
    subprocess.run(["git", "checkout", "."], cwd=workspace, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=workspace, capture_output=True)


def _is_dirty(workspace: str) -> bool:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace, capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def _current_dirty_files(workspace: str) -> frozenset:
    """Return relative paths of every dirty file (modified, staged, untracked)."""
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace, capture_output=True, text=True,
    )
    files: set[str] = set()
    for line in r.stdout.splitlines():
        if len(line) < 3:
            continue
        fname = line[3:].strip()
        if " -> " in fname:
            fname = fname.split(" -> ", 1)[1].strip()
        files.add(fname)
    return frozenset(files)


def _selective_restore(workspace: str, pre_dirty_paths: frozenset) -> None:
    """Restore only the files Claude added or modified.

    Files listed in pre_dirty_paths were already dirty before Claude ran and
    must not be touched.  All other dirty files — Claude's additions and
    modifications — are reverted or deleted.
    """
    root = Path(workspace)
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=workspace, capture_output=True, text=True,
    )
    for line in r.stdout.splitlines():
        if len(line) < 3:
            continue
        status = line[:2]
        fname = line[3:].strip()
        if " -> " in fname:
            fname = fname.split(" -> ", 1)[1].strip()
        if fname in pre_dirty_paths:
            continue  # preserve pre-existing dirty state

        path = root / fname
        if "?" in status:
            # Untracked — delete
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        else:
            # Tracked modification or staged — unstage then restore
            subprocess.run(["git", "reset", "HEAD", "--", fname], cwd=workspace, capture_output=True)
            res = subprocess.run(["git", "checkout", "--", fname], cwd=workspace, capture_output=True)
            if res.returncode != 0:
                # Newly staged file with no HEAD version — delete it
                if path.is_symlink() or path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)


def _claude_completed(stdout: str) -> bool:
    return bool(_COMPLETED_RE.search(stdout))


# ── evidence collection ───────────────────────────────────────────────────────

def _git_diff_lines(workspace: str, n: int = 30) -> list[str]:
    """Return up to n lines of the current git diff (staged + unstaged)."""
    r = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=workspace, capture_output=True, text=True,
    )
    lines = r.stdout.splitlines()
    if len(lines) > n:
        lines = lines[:n] + [f"… ({len(lines) - n} more diff lines)"]
    return lines


def _stdout_tail(stdout: str) -> list[str]:
    """Return the last portion of Claude's stdout as evidence lines."""
    text = stdout[-_EVIDENCE_STDOUT_LIMIT:] if len(stdout) > _EVIDENCE_STDOUT_LIMIT else stdout
    return text.splitlines()


# ── main validation ───────────────────────────────────────────────────────────

def validate(
    workspace: str,
    before_commit: str,
    after_commit: str,
    returncode: int,
    pre_dirty: bool = False,
    stdout: str = "",
    pre_dirty_paths: frozenset = frozenset(),
) -> ValidationResult:
    """Validate that Claude produced a clean commit.

    Returns a ValidationResult with:
      outcome  — SUCCESS / FAILURE / NO_ACTION_REQUIRED
      reason   — human-readable summary
      evidence — list of strings for diagnosis (git diff, stdout tail, exit code)

    pre_dirty: True when the working tree had uncommitted changes before Claude
    ran.  _selective_restore() is used on failure to preserve pre-existing files.

    stdout: Claude's combined stdout, used to detect the COMPLETED marker.

    pre_dirty_paths: frozenset of relative file paths dirty before Claude ran.
    """
    def safe_restore() -> None:
        if pre_dirty:
            _selective_restore(workspace, pre_dirty_paths)
        else:
            _restore(workspace)

    def make(outcome: str, reason: str, extra_evidence: list[str] | None = None) -> ValidationResult:
        evidence: list[str] = [f"exit_code={returncode}", f"outcome={outcome}"]
        if extra_evidence:
            evidence.extend(extra_evidence)
        stdout_lines = _stdout_tail(stdout)
        if stdout_lines:
            evidence.append("--- stdout (tail) ---")
            evidence.extend(stdout_lines)
        return ValidationResult(outcome=outcome, reason=reason, evidence=evidence)

    # ── non-zero exit ─────────────────────────────────────────────────────────
    if returncode != 0:
        safe_restore()
        diff = _git_diff_lines(workspace)
        prefix = "(pre-existing changes preserved)" if pre_dirty else ""
        reason = f"Claude exited with non-zero status {prefix}".rstrip()
        return make(FAILURE, reason, diff)

    # ── no new commit ─────────────────────────────────────────────────────────
    if before_commit == after_commit:
        if _claude_completed(stdout):
            current_dirty = _current_dirty_files(workspace)
            if current_dirty <= pre_dirty_paths:
                return make(NO_ACTION_REQUIRED, "Task already complete — no changes needed")
        safe_restore()
        prefix = "(pre-existing changes preserved)" if pre_dirty else ""
        reason = f"No new commit created {prefix}".rstrip()
        return make(FAILURE, reason)

    # ── dirty tree after commit ───────────────────────────────────────────────
    if _is_dirty(workspace):
        diff = _git_diff_lines(workspace)
        safe_restore()
        prefix = "(pre-existing changes preserved)" if pre_dirty else "— workspace restored"
        reason = f"Repository left dirty {prefix}".rstrip()
        return make(FAILURE, reason, diff)

    return make(SUCCESS, "Validation passed")
