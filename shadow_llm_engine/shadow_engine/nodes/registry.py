"""
Persistente Node-Registry für das Shadow-Cluster.

Speichert registrierte Nodes (Rolle, Adresse, Schlüssel, Status) in einer
JSON-Datei, sodass der Cluster-Zustand über Neustarts des Masters hinweg
erhalten bleibt. Trennung von Laufzeit-Status (in `MasterNode`) und
persistenter Registrierung (hier): die Registry ist die Quelle der Wahrheit
für "welche Nodes existieren und welche Rolle/Schlüssel haben sie".
"""

from __future__ import annotations

import json
import secrets
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from shadow_engine.nodes.base import NodeInfo, NodeRole, NodeStatus


class NodeRegistry:
    """Persistente Registrierung von Cluster-Nodes (JSON-Datei)."""

    def __init__(self, path: str | Path = "./node_registry.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({})

    # -- Low-level IO -------------------------------------------------- #
    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- CRUD ---------------------------------------------------------- #
    def add(self, info: NodeInfo, cluster_secret: Optional[str] = None) -> NodeInfo:
        """Registriert einen Node. Vergibt automatisch einen Node-Schlüssel,
        falls keiner vorhanden. Gibt den gespeicherten NodeInfo zurück."""
        with self._lock:
            data = self._read()
            entry = data.get(info.node_id, {})
            # Schlüssel vergeben, falls nicht vorhanden
            if "node_secret" not in entry:
                entry["node_secret"] = cluster_secret or secrets.token_hex(32)
            entry.update({
                "node_id": info.node_id,
                "role": info.role.value if isinstance(info.role, NodeRole) else info.role,
                "host": info.host,
                "port": info.port,
                "status": NodeStatus.ONLINE.value,
                "registered_at": info.registered_at or datetime.now(timezone.utc).isoformat(),
                "capabilities": info.capabilities,
            })
            data[info.node_id] = entry
            self._write(data)
            info.extra = {"node_secret": entry["node_secret"]}
            return info

    def get(self, node_id: str) -> Optional[dict]:
        with self._lock:
            return self._read().get(node_id)

    def list(self) -> list[dict]:
        with self._lock:
            return list(self._read().values())

    def update_status(self, node_id: str, status: NodeStatus, last_heartbeat: Optional[str] = None) -> bool:
        with self._lock:
            data = self._read()
            entry = data.get(node_id)
            if entry is None:
                return False
            entry["status"] = status.value if isinstance(status, NodeStatus) else status
            if last_heartbeat:
                entry["last_heartbeat"] = last_heartbeat
            self._write(data)
            return True

    def remove(self, node_id: str) -> bool:
        with self._lock:
            data = self._read()
            if node_id in data:
                del data[node_id]
                self._write(data)
                return True
            return False

    def filter(self, role: Optional[NodeRole] = None, status: Optional[NodeStatus] = None) -> list[dict]:
        rows = self.list()
        if role is not None:
            r = role.value if isinstance(role, NodeRole) else role
            rows = [e for e in rows if e.get("role") == r]
        if status is not None:
            s = status.value if isinstance(status, NodeStatus) else status
            rows = [e for e in rows if e.get("status") == s]
        return rows
