"""Textual-based observability dashboard for Romyq.

Launch with: romyq ui [workspace]
Install:     pip install 'romyq[ui]'
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, ScrollableContainer, Vertical
from textual.widgets import (
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from . import notes as notes_mod, store
from .findings import unresolved as findings_unresolved
from .history import recent as history_recent
from .state import load as load_state, save as save_state

# ── helpers ───────────────────────────────────────────────────────────────────

_SEV_COLORS = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "blue",
}
_SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _age(ts: str) -> str:
    """Human-readable age of an ISO timestamp."""
    if not ts:
        return "—"
    try:
        dt = datetime.fromisoformat(ts)
        age_s = int((datetime.now(timezone.utc) - dt).total_seconds())
        if age_s <= 0:
            return "just now"
        if age_s < 60:
            return f"{age_s}s"
        if age_s < 3600:
            m, s = divmod(age_s, 60)
            return f"{m}m{s:02d}s"
        h, r = divmod(age_s, 3600)
        return f"{h}h{r // 60}m"
    except Exception:
        return ts[:16]


def _md_section(path: str, heading: str) -> str:
    """Extract the content of a ## heading section from a markdown file."""
    try:
        text = Path(path).read_text()
    except Exception:
        return ""
    in_sec = False
    result: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if in_sec:
                break
            in_sec = line == f"## {heading}"
            continue
        if in_sec:
            result.append(line)
    return "\n".join(result).strip()


# ── CSS ───────────────────────────────────────────────────────────────────────

_CSS = """
Screen {
    layout: vertical;
    background: $surface;
}

/* ── status bar ── */
#status-bar {
    height: 1;
    background: $primary;
    color: $text;
    layout: horizontal;
    padding: 0 1;
}

#status-bar Label {
    height: 1;
    padding: 0 1;
    width: auto;
}

#status-badge {
    color: $success;
    text-style: bold;
}

#status-badge.completed {
    color: $warning;
}

#status-badge.stale {
    color: $error;
}

#status-badge.rate-limited {
    color: $warning;
    text-style: bold;
}

#status-badge.paused {
    color: $text-muted;
}

/* ── main split ── */
#main {
    height: 1fr;
    layout: horizontal;
}

#left-pane {
    width: 3fr;
    layout: vertical;
    border-right: solid $primary-darken-2;
}

#right-pane {
    width: 2fr;
    layout: vertical;
}

/* ── panel titles ── */
.panel-title {
    height: 1;
    background: $primary-darken-3;
    color: $text-muted;
    padding: 0 1;
    text-style: bold;
}

/* ── current task ── */
#task-panel {
    height: 8;
    border-bottom: solid $primary-darken-2;
}

#task-scroll {
    height: 1fr;
    padding: 0 1;
}

/* ── task history ── */
#history-panel {
    height: 1fr;
}

#history-table {
    height: 1fr;
}

/* ── claude output ── */
#output-panel {
    height: 11fr;
    border-bottom: solid $primary-darken-2;
}

#output-log {
    height: 1fr;
    padding: 0 1;
}

/* ── findings / notes sidebar ── */
#sidebar {
    height: 9fr;
    layout: vertical;
}

TabbedContent {
    height: 1fr;
}

TabPane {
    height: 1fr;
    padding: 0 1;
    overflow-y: auto;
}

/* ── command bar ── */
#cmd-bar {
    height: 3;
    background: $surface-darken-1;
    border-top: solid $primary-darken-2;
    layout: horizontal;
    padding: 0 1;
}

#cmd-label {
    width: auto;
    height: 1;
    content-align: left middle;
    padding: 1 0;
}

#cmd-input {
    height: 1;
    width: 1fr;
    margin: 1 0;
    border: none;
}

#cmd-hint {
    width: auto;
    height: 1;
    padding: 1 0;
    color: $text-muted;
}
"""


# ── app ───────────────────────────────────────────────────────────────────────

class RomyqDashboard(App):
    """Live observability dashboard — reads state files every 2 seconds."""

    TITLE = "romyq"
    CSS = _CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_now", "Refresh"),
    ]

    def __init__(self, workspace: str) -> None:
        super().__init__()
        self._workspace = workspace
        self._output_cache: str = ""

    # ── layout ────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        # Header row
        with Horizontal(id="status-bar"):
            yield Label("romyq")
            yield Label(f"[dim]{self._workspace}[/dim]", markup=True)
            yield Label("● starting", id="status-badge")
            yield Label("", id="stats-label")

        with Horizontal(id="main"):

            # ── Left pane ─────────────────────────────────────────────────
            with Vertical(id="left-pane"):

                with Container(id="task-panel"):
                    yield Static("Current Task", classes="panel-title")
                    with ScrollableContainer(id="task-scroll"):
                        yield Static("(waiting for first task…)", id="current-task")

                with Container(id="history-panel"):
                    yield Static("Task History", classes="panel-title")
                    table = DataTable(
                        id="history-table",
                        show_cursor=False,
                        zebra_stripes=True,
                    )
                    table.add_column("", width=2)
                    table.add_column("Time", width=5)
                    table.add_column("Mode", width=5)
                    table.add_column("Task")
                    yield table

            # ── Right pane ────────────────────────────────────────────────
            with Vertical(id="right-pane"):

                with Container(id="output-panel"):
                    yield Static("Claude Output  (last completed task)", classes="panel-title")
                    yield RichLog(
                        id="output-log",
                        highlight=False,
                        markup=False,
                        wrap=True,
                    )

                with Container(id="sidebar"):
                    with TabbedContent(initial="findings-tab"):
                        with TabPane("Findings", id="findings-tab"):
                            yield Static("", id="findings-body")
                        with TabPane("Notes", id="notes-tab"):
                            yield Static("", id="notes-body")
                        with TabPane("Knowledge", id="knowledge-tab"):
                            yield Static("", id="knowledge-body")
                        with TabPane("Steering", id="steering-tab"):
                            yield Static("", id="steering-body")

        with Horizontal(id="cmd-bar"):
            yield Label("> ", id="cmd-label")
            yield Input(
                placeholder="Type a command or instruction (help, pause, resume, stop, clear, …)",
                id="cmd-input",
            )
            yield Label("Enter to send", id="cmd-hint")

        yield Footer()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.set_interval(2.0, self._poll)
        self._poll()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle command bar submission."""
        if event.input.id != "cmd-input":
            return
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        self._handle_command(text)

    def _handle_command(self, text: str) -> None:
        """Process a command typed in the command bar."""
        cmd = text.lower().strip()

        if cmd == "help":
            self._show_help()
            return

        if cmd == "clear":
            log = self.query_one("#output-log", RichLog)
            log.clear()
            return

        if cmd in ("pause", "resume", "stop"):
            self._write_control_flag(cmd)
            return

        # Anything else is treated as an operator instruction (steering)
        try:
            from .steering import record_instruction
            record_instruction(store.events_path(self._workspace), text)
            hint = self.query_one("#cmd-hint", Label)
            hint.update(f"[green]Instruction recorded[/green]")
            self.set_timer(2.0, lambda: hint.update("Enter to send"))
        except Exception:
            pass

    def _write_control_flag(self, action: str) -> None:
        try:
            s_path = store.state_path(self._workspace)
            state = load_state(s_path)
            if action == "pause":
                state["paused"] = True
            elif action == "resume":
                state["paused"] = False
            elif action == "stop":
                state["stop_requested"] = True
            save_state(state, s_path)
            hint = self.query_one("#cmd-hint", Label)
            hint.update(f"[green]{action} sent[/green]")
            self.set_timer(2.0, lambda: hint.update("Enter to send"))
        except Exception:
            pass

    def _show_help(self) -> None:
        log = self.query_one("#output-log", RichLog)
        log.clear()
        log.write(
            "Available commands:\n"
            "  pause    — pause the loop after the current task\n"
            "  resume   — resume a paused loop\n"
            "  stop     — stop the loop gracefully\n"
            "  clear    — clear this output pane\n"
            "  help     — show this help\n\n"
            "Anything else is sent as an operator instruction to the planner.\n"
            "Examples: 'focus on tests', 'use PostgreSQL', 'skip frontend'\n"
        )

    # ── polling ───────────────────────────────────────────────────────────────

    def _poll(self) -> None:
        try:
            store.ensure_dir(self._workspace)
            state = load_state(store.state_path(self._workspace))
            self._refresh_status_bar(state)
            self._refresh_current_task(state)
            self._refresh_history()
            self._refresh_output()
            self._refresh_findings()
            self._refresh_notes()
            self._refresh_knowledge()
            self._refresh_steering()
        except Exception:
            pass

    def _refresh_status_bar(self, state: dict) -> None:
        status = state.get("status", "unknown")
        badge = self.query_one("#status-badge", Label)
        badge.remove_class("completed", "stale", "rate-limited", "paused")

        if status == "rate_limited":
            resume_at = state.get("resume_at", "")
            if resume_at:
                try:
                    resume_dt = datetime.fromisoformat(resume_at)
                    secs = max(0, int((resume_dt - datetime.now(timezone.utc)).total_seconds()))
                    mins, sec = divmod(secs, 60)
                    countdown = f"{mins}m{sec:02d}s" if mins > 0 else f"{secs}s"
                except Exception:
                    countdown = "soon"
            else:
                countdown = "soon"
            badge.update(f"● RATE LIMITED — resumes in {countdown}")
            badge.add_class("rate-limited")
        elif status == "paused":
            badge.update("● PAUSED")
            badge.add_class("paused")
        elif status == "completed":
            badge.update(f"● {status}")
            badge.add_class("completed")
        elif status == "stopped":
            badge.update(f"● {status}")
            badge.add_class("stale")
        else:
            badge.update(f"● {status}")

        hb = state.get("heartbeat", "")
        age_str = _age(hb)
        if hb:
            try:
                dt = datetime.fromisoformat(hb)
                age_s = int((datetime.now(timezone.utc) - dt).total_seconds())
                if age_s > 1800:
                    badge.add_class("stale")
                    age_str += " !"
            except Exception:
                pass

        tasks = state.get("tasks_completed", 0)
        last = (state.get("last_commit") or "—")[:12]
        self.query_one("#stats-label", Label).update(
            f"tasks: {tasks}  hb: {age_str}  commit: {last}"
        )

    def _refresh_current_task(self, state: dict) -> None:
        task = (state.get("current_task") or "").strip()
        if not task:
            text = "(waiting for first task…)"
        elif len(task) > 800:
            text = task[:797] + "…"
        else:
            text = task
        self.query_one("#current-task", Static).update(text)

    def _refresh_history(self) -> None:
        table = self.query_one("#history-table", DataTable)
        entries = history_recent(limit=200, path=store.history_path(self._workspace))
        table.clear()
        for entry in reversed(entries):
            mark = "✓" if entry["success"] else "✗"
            ts = entry["timestamp"][11:16]
            mode = (entry.get("mode") or "")[:4]
            preview = entry["task"].replace("\n", " ")[:80]
            table.add_row(mark, ts, mode, preview)

    def _refresh_output(self) -> None:
        output = _md_section(store.state_md_path(self._workspace), "Claude Output")
        if output == self._output_cache:
            return
        self._output_cache = output
        log = self.query_one("#output-log", RichLog)
        log.clear()
        log.write(output or "(no output yet)")

    def _refresh_findings(self) -> None:
        f_items = findings_unresolved(store.findings_path(self._workspace))
        if not f_items:
            text = "No unresolved findings."
        else:
            lines = []
            for f in sorted(f_items, key=lambda x: _SEV_ORDER.get(x.get("severity", "medium"), 2)):
                sev = f.get("severity", "medium")
                color = _SEV_COLORS.get(sev, "white")
                label = sev.upper()[:4]
                title = f["title"][:58]
                lines.append(f"[{color}][{label}][/{color}]  {title}")
            text = "\n".join(lines)
        self.query_one("#findings-body", Static).update(text)

    def _refresh_notes(self) -> None:
        raw = notes_mod.load(store.notes_path(self._workspace))
        lines = [ln.strip() for ln in raw.splitlines() if ln.strip().startswith("-")]
        if lines:
            text = "\n".join(lines[-20:])
        else:
            text = 'No steering notes.\nType instructions in the command bar below.'
        self.query_one("#notes-body", Static).update(text)

    def _refresh_knowledge(self) -> None:
        try:
            from . import knowledge as know_mod
            know_path = store.knowledge_path(self._workspace)
            data = know_mod.load(know_path)
            lessons = data.get("lessons", [])
            gen_at = data.get("generated_at", "")
            if not gen_at:
                text = "(knowledge not yet generated — will refresh on next run)"
            else:
                age = _age(gen_at)
                header = f"Generated {age} ago  |  {len(lessons)} lessons\n"
                lesson_lines = [f"  {i}. {l}" for i, l in enumerate(lessons[:8], 1)]
                text = header + "\n".join(lesson_lines) if lesson_lines else header + "  (no lessons)"
        except Exception:
            text = "(unavailable)"
        self.query_one("#knowledge-body", Static).update(text)

    def _refresh_steering(self) -> None:
        try:
            from .steering import recent_instructions
            instructions = recent_instructions(store.events_path(self._workspace), limit=10)
            if instructions:
                text = "\n".join(f"  • {i}" for i in reversed(instructions))
            else:
                text = "(no operator instructions yet)\n\nType instructions in the command bar."
        except Exception:
            text = "(unavailable)"
        self.query_one("#steering-body", Static).update(text)

    # ── actions ───────────────────────────────────────────────────────────────

    def action_refresh_now(self) -> None:
        self._poll()

    def action_quit(self) -> None:
        self.exit()


# ── entry point ───────────────────────────────────────────────────────────────

def launch(workspace: str) -> None:
    RomyqDashboard(workspace).run()
