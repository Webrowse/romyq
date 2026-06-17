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
) -> tuple[bool, str]:
    if returncode != 0:
        _restore(workspace)
        return False, "Claude exited with non-zero status"

    if before_commit == after_commit:
        _restore(workspace)
        return False, "No new commit created"

    if _is_dirty(workspace):
        _restore(workspace)
        return False, "Repository left dirty — workspace restored"

    return True, "Validation passed"
