"""
Checkpoint-Verwaltung für das Trainingssystem.

Getrennt von der Model Registry: Checkpoints sind Trainings-interne
Zwischenstände (inkl. Optimizer-State, Schritt-Zähler, RNG-State) für
Wiederaufnahme nach Abbruch. Die Model Registry hingegen verwaltet
fertige, versionierte Modell-"Releases" für Auslieferung/Rollback.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


@dataclass
class CheckpointMeta:
    step: int
    epoch: int
    loss: float
    extra: dict = None


class CheckpointManager:
    def __init__(self, checkpoint_dir: str | Path):
        self.checkpoint_dir = Path(checkpoint_dir)
        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def _step_dir(self, step: int) -> Path:
        return self.checkpoint_dir / f"step_{step:09d}"

    def save(
        self,
        step: int,
        epoch: int,
        loss: float,
        state_saver,
        extra: Optional[dict] = None,
    ) -> Path:
        """
        state_saver(path: Path) -> None
            Backend-Callback, das Modell- und Optimizer-State an `path` schreibt
            (z. B. torch.save({'model': ..., 'optimizer': ...}, path)).
        """
        step_dir = self._step_dir(step)
        step_dir.mkdir(parents=True, exist_ok=True)

        state_saver(step_dir / "state.bin")

        meta = CheckpointMeta(step=step, epoch=epoch, loss=loss, extra=extra or {})
        (step_dir / "meta.json").write_text(
            json.dumps(meta.__dict__, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        self._update_latest_pointer(step)
        return step_dir

    def _update_latest_pointer(self, step: int):
        (self.checkpoint_dir / "latest.json").write_text(
            json.dumps({"step": step}, indent=2), encoding="utf-8"
        )

    def latest_step(self) -> Optional[int]:
        pointer = self.checkpoint_dir / "latest.json"
        if not pointer.exists():
            return None
        return json.loads(pointer.read_text(encoding="utf-8"))["step"]

    def load(self, state_loader, step: Optional[int] = None) -> Optional[CheckpointMeta]:
        """
        state_loader(path: Path) -> None
            Backend-Callback, der Modell-/Optimizer-State aus `path` lädt.
        Gibt None zurück, wenn kein Checkpoint existiert (frischer Trainingsstart).
        """
        step = step if step is not None else self.latest_step()
        if step is None:
            return None

        step_dir = self._step_dir(step)
        if not step_dir.exists():
            return None

        state_loader(step_dir / "state.bin")
        meta = json.loads((step_dir / "meta.json").read_text(encoding="utf-8"))
        return CheckpointMeta(**meta)

    def list_checkpoints(self) -> list[int]:
        steps = []
        for d in self.checkpoint_dir.glob("step_*"):
            try:
                steps.append(int(d.name.split("_")[1]))
            except (IndexError, ValueError):
                continue
        return sorted(steps)
