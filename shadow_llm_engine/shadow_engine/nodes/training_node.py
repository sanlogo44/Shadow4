"""Training Node: führt Trainings-Berechnungen aus."""

from __future__ import annotations

from typing import Callable, Optional

from shadow_engine.nodes.base import BaseNode, NodeRole, NodeStatus


class TrainingNode(BaseNode):
    role = NodeRole.TRAINING

    def __init__(self, host: str, port: int, run_training_fn: Callable[[dict], dict], **kwargs):
        """
        run_training_fn(payload) -> result_dict
            Callback, der einen Trainingsjob tatsächlich ausführt
            (typischerweise ein ShadowTrainer.fit()-Aufruf).
        """
        super().__init__(host, port, **kwargs)
        self.run_training_fn = run_training_fn

    def execute_job(self, payload: dict) -> dict:
        self.info.status = NodeStatus.BUSY
        try:
            result = self.run_training_fn(payload)
            self.info.status = NodeStatus.ONLINE
            return {"success": True, "result": result}
        except Exception as e:
            self.info.status = NodeStatus.ERROR
            return {"success": False, "error": str(e)}
