"""Terminal-native setup wizard — pure stdin/stdout, no Textual.

Flow:
  1. What are you building?  (free text, multi-line)
  2. Select complexity       (arrow keys or numbered fallback)
  3. Generate architecture   (DeepSeek lifecycle preview)
  4. Confirm + launch        ([Y/n])

Designed so all I/O goes through injectable callables (_read_line_fn,
_keypress_fn) to make unit testing straightforward.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable


# ── ANSI helpers ──────────────────────────────────────────────────────────────

def _ansi(code: str) -> str:
    return f"\033[{code}"


def _bold(text: str) -> str:
    return f"\033[1m{text}\033[0m"


def _dim(text: str) -> str:
    return f"\033[2m{text}\033[0m"


def _cursor_up(n: int = 1) -> str:
    return f"\033[{n}A"


def _clear_line() -> str:
    return "\033[2K\r"


# ── complexity options ────────────────────────────────────────────────────────

COMPLEXITY_OPTIONS = [
    ("basic",        "Basic",        "Working software quickly — MVP, stop when it works"),
    ("intermediate", "Intermediate", "Proper architecture, tests, docs, CI"),
    ("advanced",     "Advanced",     "Production-grade: security, CI/CD, monitoring, deployment"),
]


# ── keypress reader ───────────────────────────────────────────────────────────

def _read_keypress_raw() -> str:
    """Read one keypress from stdin in raw mode. Returns 'up', 'down', 'enter', or char."""
    import tty
    import termios

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = os.read(fd, 1).decode("utf-8", errors="replace")
        if ch == "\x1b":
            ch2 = os.read(fd, 1).decode("utf-8", errors="replace")
            if ch2 == "[":
                ch3 = os.read(fd, 1).decode("utf-8", errors="replace")
                if ch3 == "A":
                    return "up"
                elif ch3 == "B":
                    return "down"
            return "escape"
        elif ch in ("\r", "\n"):
            return "enter"
        elif ch == "\x03":
            raise KeyboardInterrupt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _read_keypress_numbered() -> str:
    """Fallback: read numbered input (1/2/3) for non-TTY environments."""
    try:
        raw = sys.stdin.readline().strip()
    except (EOFError, KeyboardInterrupt):
        return "enter"
    return raw or "enter"


# ── arrow-key selector ────────────────────────────────────────────────────────

def select_option(
    options: list[tuple[str, str, str]],
    *,
    _keypress_fn: Callable[[], str] | None = None,
    _out=None,
) -> int:
    """Display an arrow-key option selector. Returns the selected index.

    Each option is (value, label, description).
    Falls back to numbered input when stdin/stdout are not TTYs.
    """
    if _out is None:
        _out = sys.stdout

    n = len(options)
    selected = 0

    is_tty = sys.stdin.isatty() and sys.stdout.isatty()

    def _render(selected_idx: int) -> None:
        for i, (_, label, desc) in enumerate(options):
            if i == selected_idx:
                print(f"  {_bold('❯ ' + label):<30}  {desc}", file=_out)
            else:
                print(f"    {label:<28}  {desc}", file=_out)

    if not is_tty:
        # Numbered fallback
        for i, (_, label, desc) in enumerate(options, 1):
            print(f"  [{i}] {label}  —  {desc}", file=_out)
        print(f"\n  Select [1-{n}]: ", end="", flush=True, file=_out)
        try:
            raw = sys.stdin.readline().strip()
        except (EOFError, KeyboardInterrupt):
            return 0
        try:
            idx = int(raw) - 1
            if 0 <= idx < n:
                return idx
        except (ValueError, TypeError):
            pass
        return 0

    # TTY mode: arrow key navigation
    keypress_fn = _keypress_fn if _keypress_fn is not None else _read_keypress_raw

    _render(selected)
    print(_dim("\n  ↑↓ arrows, Enter to select"), end="", flush=True, file=_out)

    while True:
        try:
            key = keypress_fn()
        except KeyboardInterrupt:
            print(file=_out)
            raise

        if key == "up":
            selected = (selected - 1) % n
        elif key == "down":
            selected = (selected + 1) % n
        elif key == "enter":
            print(file=_out)
            return selected
        elif key.isdigit():
            idx = int(key) - 1
            if 0 <= idx < n:
                selected = idx
                print(file=_out)
                return selected
            continue

        # Re-render: move cursor up past hint + n option lines
        sys.stdout.write(_cursor_up(n + 1))
        sys.stdout.write(_clear_line())
        _render(selected)
        print(_dim("\n  ↑↓ arrows, Enter to select"), end="", flush=True, file=_out)


# ── architecture preview ──────────────────────────────────────────────────────

def generate_architecture_preview(
    api_key: str,
    mission: str,
    complexity: str,
) -> dict | None:
    """Call DeepSeek to generate a lifecycle preview. Returns lifecycle dict or None."""
    try:
        from .lifecycle import generate as lc_generate
        lc = lc_generate(api_key, mission, complexity)
        return lc if lc.get("phases") else None
    except Exception:
        return None


def print_architecture_preview(
    lc_data: dict,
    complexity_label: str = "",
    *,
    out=None,
) -> None:
    """Print the lifecycle architecture preview."""
    if out is None:
        out = sys.stdout

    from .viz import format_lifecycle_preview

    phases = lc_data.get("phases", [])
    if not phases:
        return

    THICK = "━" * 60
    print(file=out)
    print(THICK, file=out)
    print(f"  Lifecycle  ({complexity_label})", file=out)
    print(THICK, file=out)
    print(file=out)
    print(format_lifecycle_preview(lc_data), file=out)
    print(file=out)


# ── wizard ────────────────────────────────────────────────────────────────────

def _read_mission_text(
    _read_line_fn: Callable[[str], str],
    *,
    out=None,
) -> str:
    """Read multi-line mission text from the user."""
    if out is None:
        out = sys.stdout

    print("  (blank line to finish)", file=out)
    print(file=out)
    lines: list[str] = []
    while True:
        try:
            line = _read_line_fn("  > ")
        except (EOFError, KeyboardInterrupt):
            break
        if line == "" and lines:
            break
        elif line != "":
            lines.append(line)
    return "\n".join(lines)


def run_terminal_wizard(
    workspace: str,
    api_key: str = "",
    *,
    no_vcs: bool = False,
    _keypress_fn: Callable[[], str] | None = None,
    _read_line_fn: Callable[[str], str] | None = None,
    _out=None,
    _generate_preview: bool = True,
) -> dict:
    """Run the terminal-native setup wizard.

    Returns a dict with setup results. Complexity is always required.
    Injects the selected complexity into the workspace profile before setup.
    """
    if _out is None:
        _out = sys.stdout
    if _read_line_fn is None:
        _read_line_fn = lambda prompt: input(prompt).strip()

    def pr(*args, **kwargs) -> None:
        print(*args, file=_out, **kwargs)

    THICK = "━" * 60
    SEP = "─" * 60

    # ── Header ────────────────────────────────────────────────────────────────
    pr()
    pr("  " + _bold("Romyq") + "  — Autonomous Software Project Manager")
    pr()

    # ── Mission ───────────────────────────────────────────────────────────────
    pr(SEP)
    pr("  What are you building?")
    pr(SEP)
    pr()
    mission_text = _read_mission_text(_read_line_fn, out=_out)
    if not mission_text.strip():
        from .wizard_logic import demo_mission
        mission_text = demo_mission()
        pr(f"\n  (Using demo mission)")

    pr()

    # ── Provider / API Key ────────────────────────────────────────────────────
    _key_source = ""
    if not api_key:
        import os as _os
        api_key = _os.getenv("DEEPSEEK_API_KEY", "")
        if api_key:
            _key_source = "environment"
        else:
            pr(SEP)
            pr("  Provider")
            pr(SEP)
            pr()
            pr("  Select provider: [1] DeepSeek  [2] Configure Later")
            pr()
            try:
                provider_choice = _read_line_fn("  Select [1/2]: ").strip()
            except (EOFError, KeyboardInterrupt):
                provider_choice = "2"

            if provider_choice != "2":
                pr()
                pr("  DeepSeek API Key")
                pr()
                try:
                    import getpass
                    api_key = getpass.getpass("  API Key: ").strip()
                except (EOFError, KeyboardInterrupt):
                    api_key = ""
                if api_key:
                    _key_source = "entered"
                else:
                    pr()
                    pr("  ! No API key entered.")
                    pr("    Lifecycle will use a local fallback.")
                    pr("    You can set DEEPSEEK_API_KEY later and run: romyq run")
                    pr()
            else:
                pr()
                pr("  ! No provider configured.")
                pr("    Lifecycle will use a local fallback.")
                pr("    Set DEEPSEEK_API_KEY in .env or your environment before running.")
                pr()

    if api_key and not _key_source:
        _key_source = "parameter"

    if _key_source == "environment":
        pr(SEP)
        pr("  Provider")
        pr(SEP)
        pr()
        pr("  ✓ DeepSeek — key found in environment (DEEPSEEK_API_KEY)")
        pr()

    # ── Complexity ────────────────────────────────────────────────────────────
    pr(SEP)
    pr("  Complexity")
    pr(SEP)
    pr()

    selected_idx = select_option(
        COMPLEXITY_OPTIONS,
        _keypress_fn=_keypress_fn,
        _out=_out,
    )
    complexity_key, complexity_label, _ = COMPLEXITY_OPTIONS[selected_idx]
    pr()
    pr(f"  Selected: {_bold(complexity_label)}")
    pr()

    # ── Architecture Preview ──────────────────────────────────────────────────
    lc_data: dict | None = None
    if _generate_preview and api_key:
        pr(f"  Generating lifecycle ({complexity_label})…", end="", flush=True)
        lc_data = generate_architecture_preview(api_key, mission_text, complexity_key)
        if lc_data:
            _lc_source = lc_data.get("source", "deepseek")
            if _lc_source == "local_fallback":
                pr()
                pr()
                pr("  ! DeepSeek unavailable — lifecycle uses local fallback.")
                pr("    Verify DEEPSEEK_API_KEY is valid. The fallback lifecycle")
                pr("    is generic and not tailored to your mission.")
                pr()
            else:
                pr("  done.")
                pr()
                pr("  Lifecycle generated by: DeepSeek")
            print_architecture_preview(lc_data, complexity_label, out=_out)
        else:
            pr("  (preview unavailable — lifecycle will generate on first run)")
            pr()
    elif not api_key:
        pr("  (lifecycle preview skipped — no DeepSeek API key configured)")
        pr("  Lifecycle will use a local fallback when the loop starts.")
        pr()

    # ── Confirm ───────────────────────────────────────────────────────────────
    try:
        answer = _read_line_fn("  Ready to launch? [Y/n]: ")
    except (EOFError, KeyboardInterrupt):
        answer = "n"

    if answer.lower() in ("n", "no", "q", "quit"):
        pr()
        path_arg = f" {workspace}" if workspace != "." else ""
        pr(f"  Run 'romyq run{path_arg}' when ready.")
        pr()
        _run_setup(workspace, api_key, mission_text, complexity_key, no_vcs, lc_data)
        return {}

    # ── Setup ─────────────────────────────────────────────────────────────────
    results = _run_setup(workspace, api_key, mission_text, complexity_key, no_vcs, lc_data, _out=_out)

    # ── Launch ────────────────────────────────────────────────────────────────
    pr()
    pr(THICK)
    pr("  Starting Romyq…")
    pr(THICK)
    pr()
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    from .loop import run as _run_loop
    _run_loop(workspace)

    return results


def _run_setup(
    workspace: str,
    api_key: str,
    mission_text: str,
    complexity: str,
    no_vcs: bool,
    lc_data: dict | None,
    *,
    _out=None,
) -> dict:
    """Execute the setup steps: env, mission, profile, lifecycle, git, workspace."""
    from .wizard_logic import wizard_setup
    from . import store
    from .profile import set_complexity

    results = wizard_setup(
        workspace=workspace,
        api_key=api_key,
        mission_text=mission_text,
        provider="deepseek",
        init_git=not no_vcs,
    )

    # Save complexity profile
    try:
        prof_path = store.profile_path(workspace)
        set_complexity(prof_path, complexity)
        results["profile"] = f"complexity={complexity}"
    except Exception as e:
        results["profile"] = f"failed: {e}"

    # Pre-save lifecycle if we already generated one
    if lc_data and lc_data.get("phases"):
        try:
            from .lifecycle import save as lc_save
            lc_path = store.lifecycle_path(workspace)
            lc_save(lc_path, lc_data)
            phase_count = len(lc_data["phases"])
            results["lifecycle"] = f"{phase_count} phases pre-generated"
        except Exception as e:
            results["lifecycle"] = f"failed: {e}"

    return results
