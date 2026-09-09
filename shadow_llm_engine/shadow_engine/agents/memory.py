"""
Agent Memory -- Kurz- und Langzeitgedächtnis für Shadow-Agenten.

Jeder Agent besitzt einen eigenen Speicher:
    - working_memory: flüchtige Einträge des aktuellen Laufs (Schritte, Zwischenergebnisse)
    - long_term: persistente Fakten/Ergebnisse über Läufe hinweg (key -> value)

Damit kann ein Agent auf frühere Ergebnisse zurückgreifen, Zwischenergebnisse
für spätere Schritte zwischenspeichern und kontextübergreifend lernen.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentMemory:
    working_memory: list[Any] = field(default_factory=list)
    long_term: dict[str, Any] = field(default_factory=dict)
    _max_working: int = 1000
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def remember(self, key: str, value: Any) -> None:
        with self._lock:
            self.long_term[key] = value

    def recall(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self.long_term.get(key, default)

    def forget(self, key: str) -> None:
        with self._lock:
            self.long_term.pop(key, None)

    def push_working(self, entry: Any) -> None:
        with self._lock:
            self.working_memory.append(entry)
            if len(self.working_memory) > self._max_working:
                self.working_memory = self.working_memory[-self._max_working:]

    def pop_working(self) -> Optional[Any]:
        with self._lock:
            if not self.working_memory:
                return None
            return self.working_memory.pop()

    def clear_working(self) -> None:
        with self._lock:
            self.working_memory.clear()

    def to_dict(self) -> dict:
        with self._lock:
            return {
                "working_memory": list(self.working_memory),
                "long_term": dict(self.long_term),
            }
