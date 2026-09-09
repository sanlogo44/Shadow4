"""
Node System -- Vorbereitung für ein Cluster-Setup.

Rollen:
    Master Node     verwaltet Training, Modelle, Aufgaben
    Training Node    führt Berechnungen aus
    Inference Node   führt Chat-Anfragen aus
    Storage Node     speichert Daten

Nodes werden manuell hinzugefügt (kein Auto-Discovery), wie in der
Spezifikation gefordert -- der Master führt eine explizite Registry
verbundener Nodes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class NodeRole(str, Enum):
    MASTER = "master"
    TRAINING = "training"
    INFERENCE = "inference"
    STORAGE = "storage"


class NodeStatus(str, Enum):
    OFFLINE = "offline"
    ONLINE = "online"
    BUSY = "busy"
    ERROR = "error"


@dataclass
class NodeInfo:
    node_id: str
    role: NodeRole
    host: str
    port: int
    status: NodeStatus = NodeStatus.OFFLINE
    registered_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_heartbeat: Optional[str] = None
    capabilities: dict = field(default_factory=dict)  # z. B. {"gpu_count": 2, "vram_gb": 48}


class BaseNode:
    """Gemeinsame Basis für alle Node-Rollen."""

    role: NodeRole = NodeRole.INFERENCE

    def __init__(self, host: str, port: int, node_id: Optional[str] = None, capabilities: Optional[dict] = None):
        self.info = NodeInfo(
            node_id=node_id or str(uuid.uuid4()),
            role=self.role,
            host=host,
            port=port,
            capabilities=capabilities or {},
        )

    def heartbeat(self):
        self.info.last_heartbeat = datetime.now(timezone.utc).isoformat()
        self.info.status = NodeStatus.ONLINE

    def to_dict(self) -> dict:
        return {
            "node_id": self.info.node_id,
            "role": self.info.role.value,
            "host": self.info.host,
            "port": self.info.port,
            "status": self.info.status.value,
            "registered_at": self.info.registered_at,
            "last_heartbeat": self.info.last_heartbeat,
            "capabilities": self.info.capabilities,
        }
