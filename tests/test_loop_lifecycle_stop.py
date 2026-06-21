"""Regression tests for lifecycle-completion governance in loop.py.

Verifies:
- The DeepSeek hard-stop guard fires before any generate_task() call
  when lifecycle is exhausted.
- The mission-complete + lifecycle-complete path returns without looping.
- Task 7 can never be generated after a 6-task lifecycle completes.
- DeepSeek is never called once lifecycle completion and Stop are reached.
"""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from romyq import store
from romyq.lifecycle import _build_lifecycle, _validate_phases, save as lc_save
from romyq.profile import set_complexity
from romyq.state import load as load_state, save as save_state


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_ws(tmp_path: Path) -> str:
    ws = str(tmp_path)
    store.ensure_dir(ws)
    (tmp_path / "mission.md").write_text("a calculator with pokemon 3d theme")
    return ws


def _write_basic_profile(ws: str) -> None:
    prof_path = store.profile_path(ws)
    set_complexity(prof_path, "basic")


def _write_lifecycle(ws: str, *, all_complete: bool = False) -> dict:
    phases_raw = [
        {"id": 1, "name": "Core Calculator", "tasks": [
            {"id": "1.1", "text": "Implement calculator engine"},
            {"id": "1.2", "text": "Build HTML/CSS interface"},
            {"id": "1.3", "text": "Connect engine to UI"},
        ]},
        {"id": 2, "name": "Pokemon 3D Theme", "tasks": [
            {"id": "2.1", "text": "Add Three.js dependency"},
            {"id": "2.2", "text": "Create Pikachu 3D model"},
            {"id": "2.3", "text": "Integrate 3D with calculator"},
        ]},
    ]
    phases = _validate_phases(phases_raw)
    lc = _build_lifecycle(phases, "a calculator with pokemon 3d theme", "basic", ["software runs"])
    if all_complete:
        for phase in lc["phases"]:
            phase["status"] = "complete"
            for task in phase["tasks"]:
                task["status"] = "complete"
        lc["current_phase_id"] = None
    lc_save(store.lifecycle_path(ws), lc)
    return lc


def _write_state(ws: str, **overrides) -> None:
    path = store.state_path(ws)
    state = load_state(path)
    state.update(overrides)
    save_state(state, path)


def _mock_run_env(ws: str):
    """Return a context-manager stack that stubs all external dependencies of loop.run()."""
    # We patch everything that touches the network, filesystem outside ws, or Claude.
    return [
        patch("romyq.loop.manager.evaluate_completion", return_value=(False, "not done")),
        patch("romyq.loop.manager.generate_task"),
        patch("romyq.loop.run_claude"),
        patch("romyq.loop.validate"),
        patch("romyq.loop.ws.inspect", return_value={
            "git_log": "", "git_status": "", "diff_stat": "",
            "latest_commit": "abc123",
        }),
        patch("romyq.loop.ws.bootstrap"),
        patch("romyq.loop.store.migrate", return_value=[]),
        patch("romyq.loop.activity.log"),
        patch("romyq.loop.emit"),
        patch("romyq.loop.prune_events"),
        patch("os.getenv", side_effect=lambda k, d=None: "sk-fake-key" if k == "DEEPSEEK_API_KEY" else os.environ.get(k, d)),
    ]


# ── Fix 2: DeepSeek hard-stop guard ──────────────────────────────────────────

class TestDeepSeekGuardWhenLifecycleExhausted:
    """loop.py Fix 2: hard stop before generate_task() when lifecycle is complete."""

    def test_generate_task_never_called_when_lifecycle_complete(self, tmp_path):
        """After lifecycle exhaustion, manager.generate_task must never be invoked."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        _write_lifecycle(ws, all_complete=True)
        _write_state(ws, tasks_completed=6, status="running")

        from romyq.loop import run as loop_run

        mock_generate = MagicMock()
        with patch("romyq.loop.manager.evaluate_completion", return_value=(False, "not done")), \
             patch("romyq.loop.manager.generate_task", mock_generate), \
             patch("romyq.loop.run_claude"), \
             patch("romyq.loop.ws.inspect", return_value={
                 "git_log": "", "git_status": "", "diff_stat": "", "latest_commit": "abc",
             }), \
             patch("romyq.loop.ws.bootstrap"), \
             patch("romyq.loop.store.migrate", return_value=[]), \
             patch("romyq.loop.activity.log"), \
             patch("romyq.loop.emit"), \
             patch("romyq.loop.prune_events"), \
             patch("os.getenv", side_effect=lambda k, d=None:
                   "sk-fake" if k == "DEEPSEEK_API_KEY" else os.environ.get(k, d)):
            loop_run(ws)

        mock_generate.assert_not_called()

    def test_loop_returns_when_lifecycle_complete(self, tmp_path):
        """loop.run() must return (not hang) when lifecycle is already complete at start."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        _write_lifecycle(ws, all_complete=True)
        _write_state(ws, tasks_completed=6, status="running")

        from romyq.loop import run as loop_run
        returned = []

        with patch("romyq.loop.manager.evaluate_completion", return_value=(False, "not done")), \
             patch("romyq.loop.manager.generate_task"), \
             patch("romyq.loop.run_claude"), \
             patch("romyq.loop.ws.inspect", return_value={
                 "git_log": "", "git_status": "", "diff_stat": "", "latest_commit": "abc",
             }), \
             patch("romyq.loop.ws.bootstrap"), \
             patch("romyq.loop.store.migrate", return_value=[]), \
             patch("romyq.loop.activity.log"), \
             patch("romyq.loop.emit"), \
             patch("romyq.loop.prune_events"), \
             patch("os.getenv", side_effect=lambda k, d=None:
                   "sk-fake" if k == "DEEPSEEK_API_KEY" else os.environ.get(k, d)):
            loop_run(ws)
            returned.append(True)

        assert returned == [True]

    def test_no_task7_after_6_task_lifecycle(self, tmp_path):
        """Specific regression: 6-task lifecycle complete → generate_task() call count = 0."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        _write_lifecycle(ws, all_complete=True)
        _write_state(ws, tasks_completed=6, status="running")

        from romyq.loop import run as loop_run
        generate_calls = []

        def _capture_generate(**kwargs):
            generate_calls.append(kwargs)
            return "Task 7: Add Poké Ball button"

        with patch("romyq.loop.manager.evaluate_completion", return_value=(False, "not done")), \
             patch("romyq.loop.manager.generate_task", side_effect=_capture_generate), \
             patch("romyq.loop.run_claude"), \
             patch("romyq.loop.ws.inspect", return_value={
                 "git_log": "", "git_status": "", "diff_stat": "", "latest_commit": "abc",
             }), \
             patch("romyq.loop.ws.bootstrap"), \
             patch("romyq.loop.store.migrate", return_value=[]), \
             patch("romyq.loop.activity.log"), \
             patch("romyq.loop.emit"), \
             patch("romyq.loop.prune_events"), \
             patch("os.getenv", side_effect=lambda k, d=None:
                   "sk-fake" if k == "DEEPSEEK_API_KEY" else os.environ.get(k, d)):
            loop_run(ws)

        assert generate_calls == [], (
            f"generate_task() was called {len(generate_calls)} time(s) "
            f"after lifecycle completion. First call: {generate_calls[0] if generate_calls else None}"
        )

    def test_run_claude_never_called_when_lifecycle_complete(self, tmp_path):
        """Claude is never invoked when lifecycle is already exhausted."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        _write_lifecycle(ws, all_complete=True)
        _write_state(ws, tasks_completed=6, status="running")

        from romyq.loop import run as loop_run
        mock_claude = MagicMock()

        with patch("romyq.loop.manager.evaluate_completion", return_value=(False, "not done")), \
             patch("romyq.loop.manager.generate_task"), \
             patch("romyq.loop.run_claude", mock_claude), \
             patch("romyq.loop.ws.inspect", return_value={
                 "git_log": "", "git_status": "", "diff_stat": "", "latest_commit": "abc",
             }), \
             patch("romyq.loop.ws.bootstrap"), \
             patch("romyq.loop.store.migrate", return_value=[]), \
             patch("romyq.loop.activity.log"), \
             patch("romyq.loop.emit"), \
             patch("romyq.loop.prune_events"), \
             patch("os.getenv", side_effect=lambda k, d=None:
                   "sk-fake" if k == "DEEPSEEK_API_KEY" else os.environ.get(k, d)):
            loop_run(ws)

        mock_claude.assert_not_called()

    def test_loop_stopped_event_emitted(self, tmp_path):
        """LOOP_STOPPED event must be emitted with reason=lifecycle_complete."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        _write_lifecycle(ws, all_complete=True)
        _write_state(ws, tasks_completed=6, status="running")

        from romyq.loop import run as loop_run
        from romyq.events import LOOP_STOPPED
        emitted = []

        def _capture_emit(path, event, **kwargs):
            emitted.append((event, kwargs))

        with patch("romyq.loop.manager.evaluate_completion", return_value=(False, "not done")), \
             patch("romyq.loop.manager.generate_task"), \
             patch("romyq.loop.run_claude"), \
             patch("romyq.loop.ws.inspect", return_value={
                 "git_log": "", "git_status": "", "diff_stat": "", "latest_commit": "abc",
             }), \
             patch("romyq.loop.ws.bootstrap"), \
             patch("romyq.loop.store.migrate", return_value=[]), \
             patch("romyq.loop.activity.log"), \
             patch("romyq.loop.emit", side_effect=_capture_emit), \
             patch("romyq.loop.prune_events"), \
             patch("os.getenv", side_effect=lambda k, d=None:
                   "sk-fake" if k == "DEEPSEEK_API_KEY" else os.environ.get(k, d)):
            loop_run(ws)

        stop_events = [(e, kw) for e, kw in emitted if e == LOOP_STOPPED]
        assert stop_events, "No LOOP_STOPPED event emitted"
        assert any(kw.get("reason") == "lifecycle_complete" for _, kw in stop_events), (
            f"Expected reason=lifecycle_complete but got: {[kw for _, kw in stop_events]}"
        )


# ── Fix 3: mission-complete + lifecycle-complete termination ──────────────────

class TestMissionAndLifecycleCompleteTermination:
    """loop.py Fix 3: when evaluate_completion() returns True and lifecycle is done,
    loop must stop rather than entering Continuous mode."""

    def _common_patches(self, ws, *, mission_complete=True):
        return [
            patch("romyq.loop.manager.evaluate_completion",
                  return_value=(mission_complete, "The repository contains a web calculator.")),
            patch("romyq.loop.manager.generate_task"),
            patch("romyq.loop.run_claude"),
            patch("romyq.loop.ws.inspect", return_value={
                "git_log": "", "git_status": "", "diff_stat": "", "latest_commit": "abc",
            }),
            patch("romyq.loop.ws.bootstrap"),
            patch("romyq.loop.store.migrate", return_value=[]),
            patch("romyq.loop.activity.log"),
            patch("romyq.loop.emit"),
            patch("romyq.loop.prune_events"),
            patch("os.getenv", side_effect=lambda k, d=None:
                  "sk-fake" if k == "DEEPSEEK_API_KEY" else os.environ.get(k, d)),
        ]

    def test_generate_task_not_called_on_mission_plus_lifecycle_complete(self, tmp_path):
        """When both mission and lifecycle are complete, no task is generated."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        _write_lifecycle(ws, all_complete=True)
        # tasks_completed > 0 to trigger the completion check
        _write_state(ws, tasks_completed=6, status="running")

        from romyq.loop import run as loop_run
        mock_gen = MagicMock()

        patches = self._common_patches(ws, mission_complete=True)
        patches[1] = patch("romyq.loop.manager.generate_task", mock_gen)

        import contextlib
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            loop_run(ws)

        mock_gen.assert_not_called()

    def test_loop_stops_on_mission_plus_lifecycle_complete(self, tmp_path):
        """loop.run() terminates when mission and lifecycle are both complete."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        _write_lifecycle(ws, all_complete=True)
        _write_state(ws, tasks_completed=6, status="running")

        from romyq.loop import run as loop_run
        returned = []

        import contextlib
        with contextlib.ExitStack() as stack:
            for p in self._common_patches(ws, mission_complete=True):
                stack.enter_context(p)
            loop_run(ws)
            returned.append(True)

        assert returned == [True]

    def test_fix3_guard_requires_lifecycle_complete(self, tmp_path):
        """Fix 3 only fires when all_phases_complete() is True.
        With a pending lifecycle, all_phases_complete() returns False → guard skips."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        # Lifecycle NOT fully complete (phases still pending)
        _write_lifecycle(ws, all_complete=False)

        from romyq.lifecycle import load as lc_load, all_phases_complete
        lc = lc_load(store.lifecycle_path(ws))
        # Confirm the guard condition evaluates to False for incomplete lifecycle
        assert all_phases_complete(lc) is False, (
            "Incomplete lifecycle must not trigger Fix 3 — all_phases_complete() must be False"
        )


# ── Pokemon calculator full scenario ─────────────────────────────────────────

class TestPokemonCalculatorFullScenario:
    """End-to-end simulation: basic 2-phase/6-task lifecycle at 7% readiness.

    Reproduces the exact production failure:
    - 6 lifecycle tasks complete
    - evaluate_completion() says "Mission complete"
    - Old code: enters Continuous mode, generates Task 7
    - Fixed code: stops after task 6
    """

    def _calc_lifecycle(self) -> dict:
        phases = _validate_phases([
            {"id": 1, "name": "Core Calculator", "tasks": [
                {"id": "1.1", "text": "Implement calculator engine with basic arithmetic"},
                {"id": "1.2", "text": "Build the HTML/CSS user interface"},
                {"id": "1.3", "text": "Connect engine to UI and add event listeners"},
            ]},
            {"id": 2, "name": "Pokemon 3D Theme", "tasks": [
                {"id": "2.1", "text": "Add Three.js and set up 3D scene"},
                {"id": "2.2", "text": "Create rotating Pikachu 3D model"},
                {"id": "2.3", "text": "Integrate 3D scene with calculator interface"},
            ]},
        ])
        return _build_lifecycle(
            phases,
            "a calculator with pokemon 3d theme",
            "basic",
            ["software runs"],
        )

    def test_no_pokeball_task_after_lifecycle_complete(self, tmp_path):
        """The specific regression: 'Add Poké Ball button' must never be generated."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        lc = self._calc_lifecycle()
        # Mark all 6 tasks complete
        for phase in lc["phases"]:
            phase["status"] = "complete"
            for task in phase["tasks"]:
                task["status"] = "complete"
        lc["current_phase_id"] = None
        lc_save(store.lifecycle_path(ws), lc)
        _write_state(ws, tasks_completed=6, status="running")

        from romyq.loop import run as loop_run
        poke_tasks = []

        def _capture(**kwargs):
            task_text = kwargs.get("mission", "")
            poke_tasks.append("generated")
            return "Add Poké Ball button (continuous improvement)"

        with patch("romyq.loop.manager.evaluate_completion",
                   return_value=(True, "Mission complete — The repository contains a web calculator "
                                       "with a rotating Pikachu 3D model using Three.js.")), \
             patch("romyq.loop.manager.generate_task", side_effect=_capture), \
             patch("romyq.loop.run_claude"), \
             patch("romyq.loop.ws.inspect", return_value={
                 "git_log": "", "git_status": "", "diff_stat": "", "latest_commit": "abc",
             }), \
             patch("romyq.loop.ws.bootstrap"), \
             patch("romyq.loop.store.migrate", return_value=[]), \
             patch("romyq.loop.activity.log"), \
             patch("romyq.loop.emit"), \
             patch("romyq.loop.prune_events"), \
             patch("os.getenv", side_effect=lambda k, d=None:
                   "sk-fake" if k == "DEEPSEEK_API_KEY" else os.environ.get(k, d)):
            loop_run(ws)

        assert poke_tasks == [], (
            f"generate_task() was called after lifecycle completion "
            f"({len(poke_tasks)} time(s)) — continuous improvement mode not stopped"
        )

    def test_continuous_mode_log_never_emitted(self, tmp_path):
        """'Continuous mode — proceeding with improvements.' must not appear in logs."""
        ws = _make_ws(tmp_path)
        _write_basic_profile(ws)
        lc = self._calc_lifecycle()
        for phase in lc["phases"]:
            phase["status"] = "complete"
            for task in phase["tasks"]:
                task["status"] = "complete"
        lc["current_phase_id"] = None
        lc_save(store.lifecycle_path(ws), lc)
        _write_state(ws, tasks_completed=6, status="running")

        from romyq.loop import run as loop_run
        logged = []

        with patch("romyq.loop.manager.evaluate_completion",
                   return_value=(True, "Mission complete")), \
             patch("romyq.loop.manager.generate_task"), \
             patch("romyq.loop.run_claude"), \
             patch("romyq.loop.ws.inspect", return_value={
                 "git_log": "", "git_status": "", "diff_stat": "", "latest_commit": "abc",
             }), \
             patch("romyq.loop.ws.bootstrap"), \
             patch("romyq.loop.store.migrate", return_value=[]), \
             patch("romyq.loop.activity.log", side_effect=logged.append), \
             patch("romyq.loop.emit"), \
             patch("romyq.loop.prune_events"), \
             patch("os.getenv", side_effect=lambda k, d=None:
                   "sk-fake" if k == "DEEPSEEK_API_KEY" else os.environ.get(k, d)):
            loop_run(ws)

        continuous_lines = [l for l in logged if "Continuous mode" in str(l)]
        assert continuous_lines == [], (
            f"'Continuous mode' appeared in logs after lifecycle completion: {continuous_lines}"
        )


# ── all_phases_complete helper ────────────────────────────────────────────────

class TestAllPhasesCompleteHelper:
    """Unit tests for lifecycle.all_phases_complete() which the guards depend on."""

    def test_returns_true_when_all_complete(self):
        from romyq.lifecycle import all_phases_complete
        lc = {"phases": [
            {"status": "complete"},
            {"status": "complete"},
        ]}
        assert all_phases_complete(lc) is True

    def test_returns_false_when_one_pending(self):
        from romyq.lifecycle import all_phases_complete
        lc = {"phases": [
            {"status": "complete"},
            {"status": "pending"},
        ]}
        assert all_phases_complete(lc) is False

    def test_returns_false_when_one_active(self):
        from romyq.lifecycle import all_phases_complete
        lc = {"phases": [
            {"status": "complete"},
            {"status": "active"},
        ]}
        assert all_phases_complete(lc) is False

    def test_returns_false_for_empty_lifecycle(self):
        from romyq.lifecycle import all_phases_complete
        assert all_phases_complete({"phases": []}) is False

    def test_returns_false_for_no_phases_key(self):
        from romyq.lifecycle import all_phases_complete
        assert all_phases_complete({}) is False
