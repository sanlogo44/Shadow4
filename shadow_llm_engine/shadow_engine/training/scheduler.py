"""
Scheduler: erlaubt es einem Admin, Trainingsläufe zu starten, zu stoppen,
zu pausieren und für die Zukunft zu planen -- unabhängig vom eigentlichen
Trainer, der nur auf den `TrainingSignal`-Zustand reagiert (kooperatives
Stop/Pause, kein hartes Kill).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional


class TrainingState(str, Enum):
    IDLE = "idle"
    SCHEDULED = "scheduled"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ScheduledRun:
    run_id: str
    start_at: datetime
    train_fn: Callable[[], None]
    triggered: bool = False


class TrainingSignal:
    """Thread-sicheres Signal-Objekt, das der Trainer in seiner Loop abfragt."""

    def __init__(self):
        self._pause = threading.Event()
        self._stop = threading.Event()

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    def stop(self):
        self._stop.set()

    def reset(self):
        self._pause.clear()
        self._stop.clear()

    @property
    def is_paused(self) -> bool:
        return self._pause.is_set()

    @property
    def is_stopped(self) -> bool:
        return self._stop.is_set()

    def wait_if_paused(self, poll_interval: float = 0.5):
        while self.is_paused and not self.is_stopped:
            time.sleep(poll_interval)


class TrainingScheduler:
    """
    Admin-API zur Steuerung von Trainingsläufen.

    Die eigentliche Ausführung erfolgt in einem Hintergrund-Thread; der
    Trainer selbst prüft regelmäßig `signal.is_stopped` / `is_paused`
    (siehe training/trainer.py), damit ein Stop/Pause den laufenden
    Schritt sauber beenden kann statt hart abzubrechen.
    """

    def __init__(self):
        self.state: TrainingState = TrainingState.IDLE
        self.signal = TrainingSignal()
        self._thread: Optional[threading.Thread] = None
        self._scheduled: list[ScheduledRun] = []
        self._watcher_thread: Optional[threading.Thread] = None
        self._watcher_stop = threading.Event()

    # ------------------------------------------------------------------ #
    def start(self, train_fn: Callable[[], None]):
        if self.state == TrainingState.RUNNING:
            raise RuntimeError("Es läuft bereits ein Training.")
        self.signal.reset()
        self.state = TrainingState.RUNNING

        def _run():
            try:
                train_fn()
                if not self.signal.is_stopped:
                    self.state = TrainingState.COMPLETED
                else:
                    self.state = TrainingState.STOPPED
            except Exception:
                self.state = TrainingState.FAILED
                raise

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def pause(self):
        if self.state != TrainingState.RUNNING:
            raise RuntimeError("Training läuft nicht, kann nicht pausiert werden.")
        self.signal.pause()
        self.state = TrainingState.PAUSED

    def resume(self):
        if self.state != TrainingState.PAUSED:
            raise RuntimeError("Training ist nicht pausiert.")
        self.signal.resume()
        self.state = TrainingState.RUNNING

    def stop(self):
        if self.state not in (TrainingState.RUNNING, TrainingState.PAUSED):
            raise RuntimeError("Kein aktives Training zum Stoppen.")
        self.signal.stop()
        self.signal.resume()  # falls pausiert, aufwecken damit Stop greifen kann

    # ------------------------------------------------------------------ #
    def schedule(self, run_id: str, start_at: datetime, train_fn: Callable[[], None]):
        """Plant einen Trainingslauf für einen zukünftigen Zeitpunkt."""
        self._scheduled.append(ScheduledRun(run_id=run_id, start_at=start_at, train_fn=train_fn))
        self.state = TrainingState.SCHEDULED
        self._ensure_watcher()

    def _ensure_watcher(self):
        if self._watcher_thread and self._watcher_thread.is_alive():
            return

        def _watch():
            while not self._watcher_stop.is_set():
                now = datetime.now()
                for run in self._scheduled:
                    if not run.triggered and now >= run.start_at:
                        run.triggered = True
                        self.start(run.train_fn)
                time.sleep(1.0)

        self._watcher_thread = threading.Thread(target=_watch, daemon=True)
        self._watcher_thread.start()

    def cancel_scheduled(self, run_id: str) -> bool:
        before = len(self._scheduled)
        self._scheduled = [r for r in self._scheduled if r.run_id != run_id or r.triggered]
        return len(self._scheduled) < before

    def status(self) -> dict:
        return {
            "state": self.state.value,
            "scheduled_runs": [
                {"run_id": r.run_id, "start_at": r.start_at.isoformat(), "triggered": r.triggered}
                for r in self._scheduled
            ],
        }
