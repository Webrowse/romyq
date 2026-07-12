"""Romyq init wizard — Textual-based with text-mode fallback.

Textual wizard:   requires `pip install 'romyq[ui]'`
Text-mode wizard: works with base `pip install romyq`

`run_wizard(workspace, no_vcs=False)` selects the right mode.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .wizard_logic import (
    PROVIDERS,
    demo_mission,
    validate_api_key,
    wizard_setup,
)


# ── text-mode wizard ──────────────────────────────────────────────────────────

def _print_header(title: str) -> None:
    width = 60
    print()
    print("═" * width)
    print(f"  {title}")
    print("═" * width)


def _text_wizard(workspace: str, no_vcs: bool = False) -> dict:
    """Interactive text-mode setup wizard (no Textual dependency)."""
    _print_header("Welcome to Romyq")
    print()
    print("  Autonomous AI Software Project Manager")
    print()
    print("  This wizard will configure your workspace.")
    print()

    # ── Step 1: Provider selection ────────────────────────────────────────────
    _print_header("Step 1: AI Manager")
    print()
    print("  [1] DeepSeek  (recommended)")
    print("  [N] Configure Later")
    print()
    provider = "deepseek"
    api_key = ""
    try:
        choice = input("  Select [1/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Aborted.")
        return {}

    if choice in ("n", ""):
        print()
        print("  Skipping API key setup. You can add DEEPSEEK_API_KEY to .env later.")
    else:
        # ── Step 2: API Key ──────────────────────────────────────────────────
        _print_header("Step 2: DeepSeek API Key")
        print()
        import getpass
        while True:
            try:
                api_key = getpass.getpass("  API Key: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Aborted.")
                return {}
            if validate_api_key(api_key):
                break
            print("  Key appears too short. Please re-enter.")

    # ── Step 3: Mission ───────────────────────────────────────────────────────
    _print_header("Step 3: Mission")
    print()
    print("  What do you want to build?")
    print()
    print("  [1] Demo Project  (to-do REST API)")
    print("  [P] Paste your own mission")
    print()
    try:
        mission_choice = input("  Select [1/P]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print("\n  Aborted.")
        return {}

    if mission_choice in ("1", ""):
        mission_text = demo_mission()
        print()
        print("  Using built-in demo mission (to-do REST API).")
    else:
        print()
        print("  Enter your mission (blank line to finish):")
        print()
        lines: list[str] = []
        try:
            while True:
                line = input("  ")
                if line == "":
                    if lines:
                        break
                else:
                    lines.append(line)
        except (EOFError, KeyboardInterrupt):
            pass
        mission_text = "\n".join(lines) if lines else demo_mission()

    # ── Step 4: Run setup ─────────────────────────────────────────────────────
    _print_header("Setting Up Workspace")
    print()

    results = wizard_setup(
        workspace=workspace,
        api_key=api_key,
        mission_text=mission_text,
        provider=provider,
        init_git=not no_vcs,
    )

    # ── Step 5: Summary ───────────────────────────────────────────────────────
    _print_header("Workspace Ready")
    print()

    check = lambda ok: "✓" if "failed" not in str(ok) else "✗"
    for step, result in results.items():
        mark = check(result)
        label = step.replace("_", " ").title()
        print(f"  {mark}  {label}: {result}")

    print()
    path_arg = f" {workspace}" if workspace != "." else ""
    print("  Next steps:")
    print(f"    romyq run{path_arg}")
    print()

    # Offer to start the loop immediately
    try:
        answer = input("  Start now? [Y/n]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        answer = "n"
    if answer in ("", "y", "yes"):
        print()
        _print_header("Starting Romyq")
        print()
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(workspace) / ".env")
        except Exception:
            pass
        from .loop import run as _run_loop
        _run_loop(workspace)
    else:
        print(f"\n  Run 'romyq run{path_arg}' whenever you are ready.")

    return results


# ── Textual wizard ────────────────────────────────────────────────────────────

def _textual_wizard(workspace: str, no_vcs: bool = False) -> dict:
    """Textual-based multi-screen setup wizard."""
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Container, Vertical
    from textual.widgets import Button, Footer, Header, Input, Label, Static

    _results: dict = {}

    class WizardApp(App):
        TITLE = "Romyq Setup"
        CSS = """
Screen { align: center middle; }
#wizard-box {
    width: 70;
    border: solid $primary;
    padding: 1 2;
}
.wiz-title { text-style: bold; color: $primary; margin-bottom: 1; }
.wiz-label { margin-top: 1; }
Input { margin-top: 0; }
Button { margin-top: 1; }
#status-box { margin-top: 1; color: $success; }
"""
        BINDINGS = [Binding("ctrl+c", "quit", "Quit")]

        def __init__(self) -> None:
            super().__init__()
            self._step = 0
            self._api_key = ""
            self._mission = ""
            self._provider = "deepseek"

        def compose(self) -> ComposeResult:
            yield Header(show_clock=False)
            with Container(id="wizard-box"):
                yield Static("", id="wiz-title", classes="wiz-title")
                yield Static("", id="wiz-body")
                yield Input(placeholder="", id="wiz-input", password=False)
                yield Button("Continue", id="wiz-btn", variant="primary")
                yield Static("", id="status-box")
            yield Footer()

        def on_mount(self) -> None:
            self._show_step()

        def _show_step(self) -> None:
            title = self.query_one("#wiz-title", Static)
            body = self.query_one("#wiz-body", Static)
            inp = self.query_one("#wiz-input", Input)

            if self._step == 0:
                title.update("Welcome to Romyq")
                body.update(
                    "Autonomous AI Software Project Manager\n\n"
                    "This wizard will configure your workspace.\n\n"
                    "Provider: [1] DeepSeek  [N] Configure Later\n"
                    "Type 1 or N and press Continue."
                )
                inp.placeholder = "1 or N"
                inp.password = False
                inp.value = ""
            elif self._step == 1:
                title.update("DeepSeek API Key")
                body.update(
                    "Enter your DeepSeek API key.\n"
                    "Get one at: platform.deepseek.com"
                )
                inp.placeholder = "sk-..."
                inp.password = True
                inp.value = ""
            elif self._step == 2:
                title.update("What do you want to build?")
                body.update(
                    "[1] Demo Project (to-do REST API)\n"
                    "[P] Paste your own mission\n\n"
                    "For a custom mission, type it directly below."
                )
                inp.placeholder = "1 for demo, or describe your project…"
                inp.password = False
                inp.value = ""
            elif self._step == 3:
                title.update("Setting Up Workspace…")
                body.update("Configuring API key, mission, git, and state directory.")
                inp.display = False
                btn = self.query_one("#wiz-btn", Button)
                btn.display = False
                self._run_setup()

        def _run_setup(self) -> None:
            nonlocal _results
            _results = wizard_setup(
                workspace=workspace,
                api_key=self._api_key,
                mission_text=self._mission or demo_mission(),
                provider=self._provider,
                init_git=not no_vcs,
            )
            lines = []
            for step, result in _results.items():
                mark = "✓" if "failed" not in str(result) else "✗"
                lines.append(f"  {mark}  {step.replace('_', ' ').title()}: {result}")
            self.query_one("#wiz-title", Static).update("Workspace Ready")
            self.query_one("#wiz-body", Static).update(
                "\n".join(lines) + "\n\nPress Enter or close to finish."
            )
            ok_btn = Button("Launch Romyq", id="launch-btn", variant="success")
            self.query_one("#wizard-box").mount(ok_btn)

        def on_input_submitted(self, event: object) -> None:
            self.query_one("#wiz-btn", Button).press()

        def on_button_pressed(self, event: Button.Pressed) -> None:
            if event.button.id == "launch-btn":
                self.exit(result=True)
                return
            inp = self.query_one("#wiz-input", Input)
            value = inp.value.strip()

            if self._step == 0:
                if value.lower() in ("n", ""):
                    self._provider = ""
                    self._step = 2
                else:
                    self._step = 1

            elif self._step == 1:
                if validate_api_key(value):
                    self._api_key = value
                    self._step = 2
                else:
                    self.query_one("#status-box", Static).update(
                        "Key too short — please re-enter."
                    )
                    return

            elif self._step == 2:
                if value.lower() in ("1", ""):
                    self._mission = demo_mission()
                else:
                    self._mission = value

                self._step = 3

            self.query_one("#status-box", Static).update("")
            self._show_step()

        def action_quit(self) -> None:
            self.exit()

    should_start = WizardApp().run()
    if should_start and _results:
        try:
            from dotenv import load_dotenv
            load_dotenv(Path(workspace) / ".env")
        except Exception:
            pass
        from .loop import run as _run_loop
        _run_loop(workspace)
    return _results


# ── public entry point ────────────────────────────────────────────────────────

def run_wizard(workspace: str = ".", no_vcs: bool = False, *, use_textual: bool = False) -> dict:
    """Run the terminal-native setup wizard (default).

    Pass use_textual=True (or set ROMYQ_TEXTUAL_WIZARD=1) to use the Textual UI.
    Returns the wizard_setup results dict.
    """
    import os as _os
    force_textual = use_textual or _os.getenv("ROMYQ_TEXTUAL_WIZARD", "0") == "1"

    if force_textual:
        try:
            import textual  # noqa: F401
            return _textual_wizard(workspace=workspace, no_vcs=no_vcs)
        except ImportError:
            pass  # Fall through to terminal wizard

    from .wizard_terminal import run_terminal_wizard
    return run_terminal_wizard(workspace=workspace, no_vcs=no_vcs)
