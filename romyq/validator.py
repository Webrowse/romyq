import subprocess


def _restore(path: str) -> None:
    subprocess.run(["git", "checkout", "."], cwd=path, capture_output=True)
    subprocess.run(["git", "clean", "-fd"], cwd=path, capture_output=True)


def _is_dirty(path: str) -> bool:
    r = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path, capture_output=True, text=True,
    )
    return bool(r.stdout.strip())


def validate(
    workspace: str,
    before_commit: str,
    after_commit: str,
    returncode: int,
    pre_dirty: bool = False,
) -> tuple[bool, str]:
    """Validate that Claude produced a clean commit.

    pre_dirty: True when the working tree had uncommitted changes before Claude
    ran. In that case _restore() is skipped — we must not destroy the user's
    pre-existing work. The task is still failed; the caller should warn the user
    to commit or stash their changes before running Romyq.
    """
    def safe_restore() -> None:
        if pre_dirty:
            return  # never clobber pre-existing user changes
        _restore(workspace)

    if returncode != 0:
        safe_restore()
        if pre_dirty:
            return False, "Claude exited with non-zero status (restore skipped — repo had pre-existing changes)"
        return False, "Claude exited with non-zero status"

    if before_commit == after_commit:
        safe_restore()
        if pre_dirty:
            return False, "No new commit created (restore skipped — repo had pre-existing changes)"
        return False, "No new commit created"

    if _is_dirty(workspace):
        safe_restore()
        if pre_dirty:
            return False, "Repository left dirty (restore skipped — repo had pre-existing changes)"
        return False, "Repository left dirty — workspace restored"

    return True, "Validation passed"
