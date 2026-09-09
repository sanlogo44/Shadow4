"""
Dataset Manager: orchestriert die vollständige Datenpipeline.

    Datenquelle -> Reinigung -> Qualitätsprüfung -> Tokenizer -> Trainingsdaten -> Training

Unterstützt:
    - eigene Daten (lokale Dateien / Verzeichnisse)
    - freigegebene Nutzerdaten (über einen `source_type="user_shared"`-Marker
      in den Metadaten, sodass spätere Zugriffskontrolle möglich ist)
    - spätere Crawler-Daten (über die generische `DataSource`-Schnittstelle,
      ein Crawler muss nur `iter_documents()` implementieren)
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from shadow_engine.config import DatasetConfig
from shadow_engine.dataset.cleaning import clean_documents, Deduplicator
from shadow_engine.dataset.quality import QualityFilter, QualityReport


@dataclass
class PipelineStats:
    documents_in: int = 0
    documents_after_cleaning: int = 0
    documents_after_dedup: int = 0
    documents_after_quality: int = 0

    def to_dict(self) -> dict:
        return self.__dict__


class DataSource(ABC):
    """
    Gemeinsame Schnittstelle für alle Datenquellen: lokale Dateien,
    freigegebene Nutzerdaten, spätere Crawler. Ein Crawler-Backend
    implementiert einfach diese Klasse und lässt sich ohne Änderungen
    an der übrigen Pipeline einhängen.
    """

    source_type: str = "generic"

    @abstractmethod
    def iter_documents(self) -> Iterator[str]:
        ...


class LocalDirectorySource(DataSource):
    """Liest alle .txt/.jsonl-Dateien aus einem Verzeichnis (eigene Daten)."""

    source_type = "local"

    def __init__(self, directory: str | Path, jsonl_text_field: str = "text"):
        self.directory = Path(directory)
        self.jsonl_text_field = jsonl_text_field

    def iter_documents(self) -> Iterator[str]:
        if not self.directory.exists():
            return
        for path in sorted(self.directory.rglob("*")):
            if path.suffix == ".txt":
                yield path.read_text(encoding="utf-8", errors="ignore")
            elif path.suffix == ".jsonl":
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            obj = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        text = obj.get(self.jsonl_text_field)
                        if text:
                            yield text


class UserSharedSource(DataSource):
    """
    Freigegebene Nutzerdaten. Jeder Eintrag trägt eine `consent`-Markierung;
    ohne explizite Freigabe wird das Dokument NICHT in die Pipeline
    übernommen -- Zugriffskontrolle bleibt Aufgabe der Chat-Anwendung,
    die hier nur bereits freigegebene Inhalte übergibt.
    """

    source_type = "user_shared"

    def __init__(self, documents: list[dict]):
        # documents: [{"text": ..., "consent": True, "user_id": ...}, ...]
        self.documents = documents

    def iter_documents(self) -> Iterator[str]:
        for doc in self.documents:
            if doc.get("consent") is True and doc.get("text"):
                yield doc["text"]


class CrawlerSource(DataSource):
    """
    Platzhalter für spätere Crawler-Integration. Ein konkreter Crawler
    übergibt hier lediglich einen Iterator/Generator von Rohtexten,
    der Rest der Pipeline (Reinigung/Dedup/Qualität) bleibt unverändert.
    """

    source_type = "crawler"

    def __init__(self, document_iterator: Iterator[str]):
        self._it = document_iterator

    def iter_documents(self) -> Iterator[str]:
        yield from self._it


class DatasetManager:
    def __init__(self, config: Optional[DatasetConfig] = None):
        self.config = config or DatasetConfig()
        self.quality_filter = QualityFilter(
            min_doc_length=self.config.min_doc_length,
            quality_threshold=self.config.quality_threshold,
        )

    def run_pipeline(
        self,
        sources: list[DataSource],
        output_path: Optional[str | Path] = None,
    ) -> PipelineStats:
        """Führt Reinigung -> Dedup -> Qualitätsprüfung aus und schreibt sauberes JSONL."""
        stats = PipelineStats()
        dedup = Deduplicator(method=self.config.dedupe_method)

        output_path = Path(output_path or (Path(self.config.clean_dir) / "clean.jsonl"))
        output_path.parent.mkdir(parents=True, exist_ok=True)

        def _raw_stream():
            for source in sources:
                for doc in source.iter_documents():
                    stats.documents_in += 1
                    yield doc

        with open(output_path, "w", encoding="utf-8") as out:
            for doc in clean_documents(_raw_stream()):
                stats.documents_after_cleaning += 1

                if dedup.is_duplicate(doc):
                    continue
                stats.documents_after_dedup += 1

                report: QualityReport = self.quality_filter.score(doc)
                if not report.passed:
                    continue
                stats.documents_after_quality += 1

                out.write(json.dumps({"text": doc, "quality_score": report.score}, ensure_ascii=False) + "\n")

        return stats

    def iter_clean_documents(self, path: Optional[str | Path] = None) -> Iterator[str]:
        path = Path(path or (Path(self.config.clean_dir) / "clean.jsonl"))
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)["text"]
