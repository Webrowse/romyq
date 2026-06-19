from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

# Claude's prompt instructs it to print COMPLETED when it finishes a task.
# If this marker is present, returncode is 0, and no new dirty files were
# added, the task was already complete in the repository — not a failure.
_COMPLETED_RE = re.compile(r"\bCOMPLETED\b")


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
            # Rename: "R old -> new" — track the destination
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
            # Untracked file — delete it
            if path.is_symlink() or path.is_file():
                path.unlink(missing_ok=True)
            elif path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
        else:
            # Tracked modification or staged file — unstage then restore
            subprocess.run(
                ["git", "reset", "HEAD", "--", fname],
                cwd=workspace, capture_output=True,
            )
            res = subprocess.run(
                ["git", "checkout", "--", fname],
                cwd=workspace, capture_output=True,
            )
            if res.returncode != 0:
                # File doesn't exist in HEAD (newly staged) — delete it
                if path.is_symlink() or path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)


def _claude_completed(stdout: str) -> bool:
    return bool(_COMPLETED_RE.search(stdout))


def validate(
    workspace: str,
    before_commit: str,
    after_commit: str,
    returncode: int,
    pre_dirty: bool = False,
    stdout: str = "",
    pre_dirty_paths: frozenset = frozenset(),
) -> tuple[bool, str]:
    """Validate that Claude produced a clean commit.

    pre_dirty: True when the working tree had uncommitted changes before Claude
    ran.  In that case _selective_restore() is used instead of a full restore:
    it cleans only Claude's additions while leaving pre-existing dirty files
    exactly as the user left them.

    stdout: Claude's combined stdout, used to detect the COMPLETED marker that
    signals a task was already done in the repository (no new commit needed).

    pre_dirty_paths: frozenset of file paths that were dirty before Claude ran.
    Files in this set are never touched during selective restore.
    """
    def safe_restore() -> None:
        if pre_dirty:
            _selective_restore(workspace, pre_dirty_paths)
        else:
            _restore(workspace)

    if returncode != 0:
        safe_restore()
        if pre_dirty:
            return False, "Claude exited with non-zero status (pre-existing changes preserved)"
        return False, "Claude exited with non-zero status"

    if before_commit == after_commit:
        # Claude printed COMPLETED with nothing to commit → task was already
        # done in the repository.  Only accept this if Claude left no new dirty
        # files (current dirty == pre-existing dirty or empty).
        if _claude_completed(stdout):
            current_dirty = _current_dirty_files(workspace)
            if current_dirty <= pre_dirty_paths:
                return True, "Task already complete — no changes needed"
        safe_restore()
        if pre_dirty:
            return False, "No new commit created (pre-existing changes preserved)"
        return False, "No new commit created"

    if _is_dirty(workspace):
        safe_restore()
        if pre_dirty:
            return False, "Repository left dirty (pre-existing changes preserved)"
        return False, "Repository left dirty — workspace restored"

    return True, "Validation passed"
