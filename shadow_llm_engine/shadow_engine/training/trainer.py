"""
Trainer: eigener Trainings-Loop für Shadow-Modelle.

Unterstützt:
    - Training von Null (frische Gewichte)
    - Checkpoints (siehe training/checkpoint.py)
    - Wiederaufnahme nach Abbruch
    - Evaluation in festen Intervallen
    - kooperatives Pause/Stop über TrainingScheduler.signal

Der Trainer ist bewusst an PyTorch gebunden (Referenz-Backend), da ein
Trainings-Loop naturgemäß eng mit Autograd/Optimizer der jeweiligen
Bibliothek verzahnt ist. Ein JAX-Trainer würde dasselbe `TrainerCallbacks`-
Protokoll implementieren, sodass Scheduler/Checkpoint/Registry unverändert
weiterverwendet werden können.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

from shadow_engine.config import TrainingConfig
from shadow_engine.training.checkpoint import CheckpointManager
from shadow_engine.training.scheduler import TrainingSignal

try:
    import torch
    from torch.utils.data import DataLoader
    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TORCH_AVAILABLE = False
    torch = None


@dataclass
class TrainStepResult:
    step: int
    loss: float
    learning_rate: float


class LinearWarmupCosineDecay:
    """LR-Schedule: linearer Warmup gefolgt von Cosine-Decay bis 10% der Peak-LR."""

    def __init__(self, base_lr: float, warmup_steps: int, max_steps: int, min_lr_ratio: float = 0.1):
        self.base_lr = base_lr
        self.warmup_steps = max(1, warmup_steps)
        self.max_steps = max(1, max_steps)
        self.min_lr_ratio = min_lr_ratio

    def get_lr(self, step: int) -> float:
        import math
        if step < self.warmup_steps:
            return self.base_lr * step / self.warmup_steps
        progress = min(1.0, (step - self.warmup_steps) / max(1, self.max_steps - self.warmup_steps))
        cosine = 0.5 * (1 + math.cos(math.pi * progress))
        return self.base_lr * (self.min_lr_ratio + (1 - self.min_lr_ratio) * cosine)


class ShadowTrainer:
    def __init__(
        self,
        model,
        config: TrainingConfig,
        device: str = "cpu",
        signal: Optional[TrainingSignal] = None,
        on_step: Optional[Callable[[TrainStepResult], None]] = None,
        on_eval: Optional[Callable[[dict], None]] = None,
    ):
        if not _TORCH_AVAILABLE:
            raise RuntimeError("PyTorch wird für ShadowTrainer benötigt.")

        self.model = model.to(device)
        self.config = config
        self.device = device
        self.signal = signal or TrainingSignal()
        self.on_step = on_step
        self.on_eval = on_eval

        self.optimizer = torch.optim.AdamW(
            self.model.parameters(), lr=config.learning_rate, weight_decay=config.weight_decay
        )
        self.lr_schedule = LinearWarmupCosineDecay(
            config.learning_rate, config.warmup_steps, config.max_steps
        )
        self.checkpoints = CheckpointManager(config.checkpoint_dir)
        self.global_step = 0
        self.epoch = 0

    # ------------------------------------------------------------------ #
    def _state_saver(self, path: Path):
        torch.save({
            "model": self.model.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "step": self.global_step,
            "epoch": self.epoch,
        }, path)

    def _state_loader(self, path: Path):
        blob = torch.load(path, map_location=self.device)
        self.model.load_state_dict(blob["model"])
        self.optimizer.load_state_dict(blob["optimizer"])
        self.global_step = blob["step"]
        self.epoch = blob["epoch"]

    def resume_if_available(self) -> bool:
        """Versucht, vom letzten Checkpoint fortzusetzen. True, falls erfolgreich."""
        meta = self.checkpoints.load(self._state_loader)
        return meta is not None

    # ------------------------------------------------------------------ #
    def train_step(self, batch: dict) -> TrainStepResult:
        self.model.train()
        input_ids = batch["input_ids"].to(self.device)
        labels = batch.get("labels", input_ids).to(self.device)

        lr = self.lr_schedule.get_lr(self.global_step)
        for group in self.optimizer.param_groups:
            group["lr"] = lr

        out = self.model(input_ids=input_ids, labels=labels)
        loss = out["loss"] / self.config.grad_accum_steps
        loss.backward()

        if (self.global_step + 1) % self.config.grad_accum_steps == 0:
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 1.0)
            self.optimizer.step()
            self.optimizer.zero_grad()

        self.global_step += 1
        return TrainStepResult(step=self.global_step, loss=out["loss"].item(), learning_rate=lr)

    @torch.no_grad()
    def evaluate(self, eval_batches: Iterable[dict]) -> dict:
        self.model.eval()
        total_loss, n = 0.0, 0
        for batch in eval_batches:
            input_ids = batch["input_ids"].to(self.device)
            labels = batch.get("labels", input_ids).to(self.device)
            out = self.model(input_ids=input_ids, labels=labels)
            total_loss += out["loss"].item()
            n += 1
        avg_loss = total_loss / max(n, 1)
        import math
        return {"eval_loss": avg_loss, "perplexity": math.exp(min(avg_loss, 20))}

    # ------------------------------------------------------------------ #
    def fit(
        self,
        train_loader: Iterable[dict],
        eval_loader: Optional[Iterable[dict]] = None,
        resume: bool = True,
    ):
        """Führt die vollständige Trainingsschleife bis `max_steps` oder Stop-Signal aus."""
        if resume:
            resumed = self.resume_if_available()
            if resumed and self.on_step:
                pass  # Logging optional durch Aufrufer

        while self.global_step < self.config.max_steps:
            for batch in train_loader:
                if self.signal.is_stopped:
                    return
                self.signal.wait_if_paused()
                if self.signal.is_stopped:
                    return

                result = self.train_step(batch)
                if self.on_step:
                    self.on_step(result)

                if self.global_step % self.config.checkpoint_every == 0:
                    self.checkpoints.save(
                        self.global_step, self.epoch, result.loss, self._state_saver
                    )

                if eval_loader is not None and self.global_step % self.config.eval_every == 0:
                    metrics = self.evaluate(eval_loader)
                    if self.on_eval:
                        self.on_eval(metrics)

                if self.global_step >= self.config.max_steps:
                    break
            self.epoch += 1

        # Finaler Checkpoint am Ende des Laufs
        self.checkpoints.save(self.global_step, self.epoch, 0.0, self._state_saver)
