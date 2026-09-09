"""Inference Node: führt Chat-Anfragen (Textgenerierung) aus."""

from __future__ import annotations

from typing import Callable

from shadow_engine.nodes.base import BaseNode, NodeRole, NodeStatus


class InferenceNode(BaseNode):
    role = NodeRole.INFERENCE

    def __init__(self, host: str, port: int, generate_fn: Callable[[dict], str], **kwargs):
        """
        generate_fn(payload) -> generated_text
            Callback, der eine Chat-Anfrage tatsächlich gegen ein geladenes
            Shadow-Modell ausführt (siehe api/server.py für die Anbindung
            an die Model Registry).
        """
        super().__init__(host, port, **kwargs)
        self.generate_fn = generate_fn

    def execute_job(self, payload: dict) -> dict:
        self.info.status = NodeStatus.BUSY
        try:
            text = self.generate_fn(payload)
            self.info.status = NodeStatus.ONLINE
            return {"success": True, "result": {"text": text}}
        except Exception as e:
            self.info.status = NodeStatus.ERROR
            return {"success": False, "error": str(e)}
