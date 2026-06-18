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
    Label,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from . import notes as notes_mod, store
from .findings import unresolved as findings_unresolved
from .history import recent as history_recent
from .state import load as load_state

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

        yield Footer()

    # ── lifecycle ─────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        self.set_interval(2.0, self._poll)
        self._poll()

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
        except Exception:
            pass

    def _refresh_status_bar(self, state: dict) -> None:
        status = state.get("status", "unknown")
        badge = self.query_one("#status-badge", Label)
        badge.update(f"● {status}")
        badge.remove_class("completed", "stale")
        if status == "completed":
            badge.add_class("completed")

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
            text = 'No steering notes.\nAdd with: romyq note "message"'
        self.query_one("#notes-body", Static).update(text)

    # ── actions ───────────────────────────────────────────────────────────────

    def action_refresh_now(self) -> None:
        self._poll()

    def action_quit(self) -> None:
        self.exit()


# ── entry point ───────────────────────────────────────────────────────────────

def launch(workspace: str) -> None:
    RomyqDashboard(workspace).run()
