"""
Audit-Log für die Shadow-Sicherheitslayer.

Append-only Protokoll aller sicherheitsrelevanten Operationen:
Schlüsselerzeugung, Rotation, Backup, Ver- und Entschlüsselung,
Zugriffsverweigerungen. Persistiert als JSONL (eine Zeile pro Ereignis).
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class AuditLog:
    def __init__(self, path: str | Path = "./audit.log"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log(self, action: str, actor: str = "system", detail: Optional[dict] = None,
            outcome: str = "success") -> dict:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "actor": actor,
            "outcome": outcome,
            "detail": detail or {},
        }
        with self._lock:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def entries(self) -> list[dict]:
        if not self.path.exists():
            return []
        rows = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return rows

    def filter(self, action: Optional[str] = None, outcome: Optional[str] = None) -> list[dict]:
        rows = self.entries()
        if action:
            rows = [r for r in rows if r.get("action") == action]
        if outcome:
            rows = [r for r in rows if r.get("outcome") == outcome]
        return rows
