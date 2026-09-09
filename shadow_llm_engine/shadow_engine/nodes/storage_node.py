"""Storage Node: speichert Daten (Datasets, Checkpoints, Modell-Artefakte)."""

from __future__ import annotations

import shutil
from pathlib import Path

from shadow_engine.nodes.base import BaseNode, NodeRole, NodeStatus


class StorageNode(BaseNode):
    role = NodeRole.STORAGE

    def __init__(self, host: str, port: int, storage_root: str | Path, **kwargs):
        super().__init__(host, port, **kwargs)
        self.storage_root = Path(storage_root)
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def put(self, relative_path: str, data: bytes) -> dict:
        self.info.status = NodeStatus.BUSY
        try:
            target = self.storage_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            self.info.status = NodeStatus.ONLINE
            return {"success": True, "path": str(target)}
        except Exception as e:
            self.info.status = NodeStatus.ERROR
            return {"success": False, "error": str(e)}

    def get(self, relative_path: str) -> bytes:
        return (self.storage_root / relative_path).read_bytes()

    def delete(self, relative_path: str):
        target = self.storage_root / relative_path
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

    def usage_report(self) -> dict:
        total_size = sum(f.stat().st_size for f in self.storage_root.rglob("*") if f.is_file())
        return {"root": str(self.storage_root), "total_bytes": total_size}
