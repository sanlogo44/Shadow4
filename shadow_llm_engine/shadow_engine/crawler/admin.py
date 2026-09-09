"""
Crawler-Admin-Kontrolle: Quellen verwalten, Crawling planen, Daten prüfen.

Der Admin entscheidet, welche Domains erlaubt/blockiert sind, wann gecrawlt
wird (Schedule) und kann gesammelte Daten vor der Übernahme in das
Training-Dataset prüfen (Review). Persistenz als JSON.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class CrawlSchedule:
    enabled: bool = False
    cron: str = "0 2 * * *"          # tägliche 02:00 UTC
    seed_urls: list[str] = field(default_factory=list)
    max_pages: int = 1000
    last_run: Optional[str] = None


@dataclass
class ReviewEntry:
    url: str
    text_preview: str
    quality_score: float
    status: str = "pending"          # pending | approved | rejected
    reviewed_at: Optional[str] = None


class CrawlerAdmin:
    """Verwaltet Allow-/Block-Listen, Schedule und Daten-Review (persistent)."""

    def __init__(self, path: str | Path = "./crawler_admin.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write({"allowed": [], "blocked": [], "schedule": CrawlSchedule().__dict__,
                         "review_queue": []})

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            return {"allowed": [], "blocked": [], "schedule": CrawlSchedule().__dict__,
                    "review_queue": []}

    def _write(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Quellen ----------------------------------------------------------- #
    def allow(self, domain: str) -> None:
        with self._lock:
            data = self._read()
            if domain not in data["allowed"]:
                data["allowed"].append(domain)
            if domain in data["blocked"]:
                data["blocked"].remove(domain)
            self._write(data)

    def block(self, domain: str) -> None:
        with self._lock:
            data = self._read()
            if domain not in data["blocked"]:
                data["blocked"].append(domain)
            if domain in data["allowed"]:
                data["allowed"].remove(domain)
            self._write(data)

    def allowed_domains(self) -> list[str]:
        with self._lock:
            return list(self._read().get("allowed", []))

    def blocked_domains(self) -> list[str]:
        with self._lock:
            return list(self._read().get("blocked", []))

    # Schedule ---------------------------------------------------------- #
    def set_schedule(self, schedule: CrawlSchedule) -> None:
        with self._lock:
            data = self._read()
            data["schedule"] = schedule.__dict__
            self._write(data)

    def get_schedule(self) -> CrawlSchedule:
        with self._lock:
            data = self._read()
            sched = data.get("schedule", {})
            return CrawlSchedule(**{k: v for k, v in sched.items() if k in CrawlSchedule.__dataclass_fields__})

    def mark_run(self) -> None:
        with self._lock:
            data = self._read()
            data.setdefault("schedule", {})["last_run"] = datetime.now(timezone.utc).isoformat()
            self._write(data)

    # Review ------------------------------------------------------------- #
    def submit_for_review(self, entry: ReviewEntry) -> None:
        with self._lock:
            data = self._read()
            data.setdefault("review_queue", []).append(entry.__dict__)
            self._write(data)

    def pending_reviews(self) -> list[dict]:
        with self._lock:
            data = self._read()
            return [r for r in data.get("review_queue", []) if r.get("status") == "pending"]

    def review(self, url: str, approved: bool) -> bool:
        with self._lock:
            data = self._read()
            for r in data.get("review_queue", []):
                if r.get("url") == url and r.get("status") == "pending":
                    r["status"] = "approved" if approved else "rejected"
                    r["reviewed_at"] = datetime.now(timezone.utc).isoformat()
                    self._write(data)
                    return True
        return False
