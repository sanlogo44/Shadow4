"""
Shadow DataLoader -- produktionsfähiger Daten-Loader für das Trainingssystem.

Format-Reader (alle streaming / lazy, kein vollständiges Einlesen nötig):
    - JSONL   (.jsonl)
    - JSON    (.json)        -- Array oder Zeilen-Array
    - TXT     (.txt)
    - CSV     (.csv)
    - Parquet (.parquet)     -- optional, benötigt pyarrow/pandas

Pipeline (jede Phase ist ein reiner Generator):

    Rohdaten
        |
    Validierung          (Format/Encoding prüfen, Leerzeilen verwerfen)
        |
    Bereinigung          (Unicode/HTML/Steuerzeichen, Whitespace)
        |
    Duplikat-Erkennung   (exact / simhash, State im Deduplicator)
        |
    Qualitätsbewertung   (Länge, Buchstabenanteil, Repetition)
        |
    Tokenisierung        (austauschbare tokenize_fn -> Token-IDs)
        |
    Training Dataset     (JSONL mit {"input_ids": [...], "text": ...})
        |
    Batch Loader         (Streaming, gepuffertes Shuffeln, Batches,
                          Checkpoints, Wiederaufnahme, verteiltes Sharding)

Alle schweren Abhängigkeiten (pyarrow/pandas für Parquet, torch für
Tensoren) sind optional: der Loader läuft mit reinen Standardbibliotheken,
Parquet wird nur dann angeboten, wenn das Backend installiert ist.
"""

from __future__ import annotations

import csv
import io
import json
import os
import random
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

# ---------------------------------------------------------------------- #
# Dokument-Typ
# ---------------------------------------------------------------------- #


@dataclass
class Document:
    """Ein einzelnes Rohdokument mit Herkunfts-Metadaten."""

    text: str
    source: str = ""
    index: int = 0
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"text": self.text, "source": self.source, "index": self.index, **self.extra}


# ---------------------------------------------------------------------- #
# Format-Reader (streaming)
# ---------------------------------------------------------------------- #
# Jeder Reader ist ein Generator (path -> Iterator[Document]) und liest
# die Datei zeilen- bzw. stückweise, sodass auch sehr große Dateien
# ohne vollständiges Einlesen in den Speicher verarbeitet werden können.


def read_txt(path: str | Path, text_field: str = "text") -> Iterator[Document]:
    """Liest eine .txt-Datei. Ein Absatz (durch Leerzeile getrennt) = ein Dokument,
    falls `split_paragraphs=True`; sonst die ganze Datei als ein Dokument."""
    path = Path(path)
    # Default: ganzes Dokument. Wenn der Inhalt Absätze enthält, aufspalten.
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        buffer: list[str] = []
        idx = 0
        for line in f:
            if line.strip() == "":
                if buffer:
                    yield Document(text="".join(buffer).strip(), source=str(path), index=idx)
                    idx += 1
                    buffer = []
            else:
                buffer.append(line)
        if buffer:
            yield Document(text="".join(buffer).strip(), source=str(path), index=idx)


def read_jsonl(path: str | Path, text_field: str = "text") -> Iterator[Document]:
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            text = obj.get(text_field) if isinstance(obj, dict) else None
            if text:
                extra = {k: v for k, v in obj.items() if k != text_field}
                yield Document(text=text, source=str(path), index=i, extra=extra)


def read_json(path: str | Path, text_field: str = "text") -> Iterator[Document]:
    """Liest eine .json-Datei. Erwartet wird ein Array von Objekten mit
    einem Text-Feld (oder ein einzelnes Objekt)."""
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return
    for i, obj in enumerate(data):
        if not isinstance(obj, dict):
            continue
        text = obj.get(text_field)
        if text:
            extra = {k: v for k, v in obj.items() if k != text_field}
            yield Document(text=text, source=str(path), index=i, extra=extra)


def read_csv(path: str | Path, text_field: str = "text") -> Iterator[Document]:
    path = Path(path)
    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            return
        fieldname = text_field if text_field in reader.fieldnames else reader.fieldnames[0]
        for i, row in enumerate(reader):
            text = (row.get(fieldname) or "").strip()
            if text:
                extra = {k: v for k, v in row.items() if k != fieldname}
                yield Document(text=text, source=str(path), index=i, extra=extra)


def read_parquet(path: str | Path, text_field: str = "text") -> Iterator[Document]:
    """Liest eine .parquet-Datei streaming über pyarrow. Optional -- parquet
    wird nur unterstützt, wenn pyarrow (oder pandas+pyarrow) installiert ist."""
    try:
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:  # pragma: no cover - abhängig von Umgebung
        raise RuntimeError(
            "Parquet-Unterstützung benötigt 'pyarrow' (pip install pyarrow)."
        ) from exc

    path = Path(path)
    pf = pq.ParquetFile(path)
    columns = pf.schema_arrow.names
    col = text_field if text_field in columns else columns[0]
    row_index = 0
    for batch in pf.iter_batches(batch_size=1024, columns=[col]):
        col_data = batch.column(0).to_pylist()
        for value in col_data:
            text = (str(value) if value is not None else "").strip()
            if text:
                yield Document(text=text, source=str(path), index=row_index)
            row_index += 1


# Registry: Dateiendung -> Reader-Funktion
FORMAT_READERS: dict[str, Callable[..., Iterator[Document]]] = {
    ".txt": read_txt,
    ".jsonl": read_jsonl,
    ".json": read_json,
    ".csv": read_csv,
    ".parquet": read_parquet,
}

SUPPORTED_FORMATS = tuple(FORMAT_READERS.keys())


def reader_for(path: str | Path) -> Optional[Callable[..., Iterator[Document]]]:
    suffix = Path(path).suffix.lower()
    return FORMAT_READERS.get(suffix)


def iter_files(root: str | Path, recursive: bool = True) -> Iterator[Path]:
    """Iteriert alle unterstützten Daten-Dateien unter `root` (sortiert)."""
    root = Path(root)
    if not root.exists():
        return
    if root.is_file():
        yield root
        return
    paths = root.rglob("*") if recursive else root.glob("*")
    for p in sorted(paths):
        if p.is_file() and p.suffix.lower() in FORMAT_READERS:
            yield p


def read_file(path: str | Path, text_field: str = "text") -> Iterator[Document]:
    """Dispatcht anhand der Dateiendung an den passenden Reader."""
    reader = reader_for(path)
    if reader is None:
        raise ValueError(f"Nicht unterstütztes Dateiformat: {path} ({Path(path).suffix})")
    yield from reader(path, text_field=text_field)


# ---------------------------------------------------------------------- #
# Validierung
# ---------------------------------------------------------------------- #


def validate_document(doc: Document, min_length: int = 1) -> Optional[Document]:
    """Wirft leere / unbrauchbare Dokumente weg. Liefert None, falls ungültig."""
    text = (doc.text or "").strip()
    if len(text) < min_length:
        return None
    doc.text = text
    return doc


# ---------------------------------------------------------------------- #
# Datenpipeline
# ---------------------------------------------------------------------- #


# Tokenizer-Funktion: (text) -> list[int]
TokenizeFn = Callable[[str], list[int]]


def identity_tokenize(text: str) -> list[int]:
    """Fallback-Tokenizer: UTF-8-Bytes als Token-IDs (sprachunabhängig)."""
    return list(text.encode("utf-8"))


@dataclass
class PipelineStats:
    documents_in: int = 0
    documents_after_validation: int = 0
    documents_after_cleaning: int = 0
    documents_after_dedup: int = 0
    documents_after_quality: int = 0
    documents_after_tokenization: int = 0

    def to_dict(self) -> dict:
        return self.__dict__


class DataPipeline:
    """
    Orchestriert die vollständige Pipeline als verkettete Generatoren:

        Rohdaten -> Validierung -> Bereinigung -> Duplikat-Erkennung
                 -> Qualitätsbewertung -> Tokenisierung -> Training Dataset

    Jede Phase ist ein reiner Generator, sodass die Pipeline komplett
    streaming-fähig ist: auch Terabyte-Datenmengen fließen Dokument für
    Dokument durch, ohne jemals vollständig im Speicher zu stehen.

    `tokenize_fn` ist austauschbar (Default: Byte-Fallback). Ohne Angabe
    wird nur bereinigt/dedupiziert/gefiltert, aber nicht tokenisiert.
    """

    def __init__(
        self,
        min_doc_length: int = 20,
        dedupe_method: str = "simhash",
        quality_threshold: float = 0.5,
        tokenize_fn: Optional[TokenizeFn] = None,
        text_field: str = "text",
    ):
        # Lokaler Import, um Zirkelimporte zu vermeiden.
        from shadow_engine.dataset.cleaning import clean_documents, Deduplicator
        from shadow_engine.dataset.quality import QualityFilter

        self.min_doc_length = min_doc_length
        self.dedup = Deduplicator(method=dedupe_method)
        self.quality_filter = QualityFilter(
            min_doc_length=min_doc_length, quality_threshold=quality_threshold
        )
        self.tokenize_fn = tokenize_fn
        self.text_field = text_field
        self._clean_documents = clean_documents

    def run(self, sources: Iterator[Document]) -> tuple[Iterator[dict], PipelineStats]:
        """Verkettet alle Phasen. Gibt (training_examples_iterator, stats) zurück.

        WICHTIG: da alles Generatoren sind, wird `stats` erst befüllt, wenn
        der zurückgegebene Iterator vollständig konsumiert wurde."""
        stats = PipelineStats()

        def _validated():
            for doc in sources:
                stats.documents_in += 1
                v = validate_document(doc, min_length=1)
                if v is not None:
                    stats.documents_after_validation += 1
                    yield v.text

        def _cleaned():
            for text in self._clean_documents(_validated()):
                stats.documents_after_cleaning += 1
                yield text

        def _deduped():
            for text in _cleaned():
                if not self.dedup.is_duplicate(text):
                    stats.documents_after_dedup += 1
                    yield text

        def _quality():
            for text in _deduped():
                report = self.quality_filter.score(text)
                if report.passed:
                    stats.documents_after_quality += 1
                    yield text

        def _tokenized():
            for text in _quality():
                if self.tokenize_fn is not None:
                    ids = self.tokenize_fn(text)
                    if ids:
                        stats.documents_after_tokenization += 1
                        yield {"input_ids": ids, "text": text}
                else:
                    stats.documents_after_tokenization += 1
                    yield {"text": text}

        return _tokenized(), stats


# ---------------------------------------------------------------------- #
# Batch Loader (streaming, shuffle, checkpoints, verteiltes Sharding)
# ---------------------------------------------------------------------- #


@dataclass
class BatchCheckpoint:
    epoch: int
    consumed: int          # Anzahl bisher konsumierter Beispiele (global, über Epochen)
    rng_state: tuple
    shuffle_seed: int


class BatchLoader:
    """
    Streaming-Batch-Loader mit:

    - gepuffertem Shuffeln (shuffle_buffer): ein endlicher Puffer wird
      gefüllt und zufällig entnommen -> echte Shuffelung auch bei
      Streaming-Quellen, ohne die gesamte Datenmenge im Speicher zu halten.
    - Checkpoints: Position (epoch, consumed) + RNG-State werden gespeichert
      und beim Wiederaufnehmen exakt wiederhergestellt -> reproduzierbares
      Weitertrainieren nach Absturz.
    - verteiltes Sharding: rank/world_size teilen die Daten deterministisch
      auf mehrere Worker/GPUs/Nodes auf.

    `dataset` ist ein Iterable von Beispiel-Dicts (z. B. {"input_ids": ...}).
    Für echtes Streaming kann ein Generator übergeben werden; `epochs`
    bestimmt, wie oft über die Quelle iteriert wird (wiederholbare Epochen
    für Shuffle + Resume).
    """

    def __init__(
        self,
        dataset,
        batch_size: int = 8,
        shuffle: bool = True,
        shuffle_buffer: int = 10_000,
        seed: int = 1337,
        drop_last: bool = False,
        epochs: int = 1,
        rank: int = 0,
        world_size: int = 1,
        checkpoint_path: Optional[str | Path] = None,
    ):
        if batch_size < 1:
            raise ValueError("batch_size muss >= 1 sein")
        if world_size < 1 or not (0 <= rank < world_size):
            raise ValueError("rank muss in [0, world_size) liegen")
        self.dataset = dataset
        self.batch_size = batch_size
        self.shuffle = shuffle
        self.shuffle_buffer = max(1, shuffle_buffer)
        self.seed = seed
        self.drop_last = drop_last
        self.epochs = max(1, epochs)
        self.rank = rank
        self.world_size = world_size
        self.checkpoint_path = Path(checkpoint_path) if checkpoint_path else None
        self.consumed = 0
        self.epoch = 0
        self._rng = random.Random(seed)

    # -- Checkpoints --------------------------------------------------- #
    def save_checkpoint(self) -> BatchCheckpoint:
        cp = BatchCheckpoint(
            epoch=self.epoch,
            consumed=self.consumed,
            rng_state=self._rng.getstate(),
            shuffle_seed=self.seed,
        )
        if self.checkpoint_path is not None:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            self.checkpoint_path.write_text(
                json.dumps(
                    {"epoch": cp.epoch, "consumed": cp.consumed, "rng_state": list(cp.rng_state),
                     "shuffle_seed": cp.shuffle_seed},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        return cp

    def load_checkpoint(self) -> bool:
        if self.checkpoint_path is None or not self.checkpoint_path.exists():
            return False
        data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        self.epoch = data["epoch"]
        self.consumed = data["consumed"]

        def _to_tuple(obj):
            if isinstance(obj, list):
                return tuple(_to_tuple(x) for x in obj)
            return obj

        self._rng.setstate(_to_tuple(data["rng_state"]))
        return True

    # -- Streaming ------------------------------------------------------ #
    def _sharded_stream(self):
        """Verteiltes Sharding: jeder rank sieht nur sein 1/world_size-Teil
        der Beispiele (deterministisch, mod-basiert)."""
        global_index = 0
        for epoch in range(self.epochs):
            self.epoch = epoch
            for example in self._iter_dataset():
                if self.world_size > 1 and (global_index % self.world_size) != self.rank:
                    global_index += 1
                    continue
                global_index += 1
                yield example

    def _iter_dataset(self):
        """Erlaubt Iterable und erneuerbare Generatoren (Callable)."""
        if callable(self.dataset) and not hasattr(self.dataset, "__iter__"):
            return iter(self.dataset())
        return iter(self.dataset)

    def _shuffle_buffer_stream(self, stream: Iterator):
        """Gepuffertes Shuffeln über einen Stream: füllt einen Puffer bis
        shuffle_buffer, entnimmt dann zufällig und füllt nach."""
        if not self.shuffle:
            yield from stream
            return
        buffer: list = []
        for item in stream:
            buffer.append(item)
            if len(buffer) >= self.shuffle_buffer:
                yield buffer.pop(self._rng.randint(0, len(buffer) - 1))
        # Rest flushen (zufällige Reihenfolge)
        self._rng.shuffle(buffer)
        yield from buffer

    def __iter__(self) -> Iterator[list]:
        """Liefert Batches (Listen von Beispielen)."""
        stream = self._sharded_stream()
        stream = self._shuffle_buffer_stream(stream)

        batch: list = []
        for example in stream:
            batch.append(example)
            self.consumed += 1
            if len(batch) == self.batch_size:
                yield batch
                batch = []
                if self.checkpoint_path is not None:
                    self.save_checkpoint()
        if batch and not self.drop_last:
            yield batch
        if self.checkpoint_path is not None:
            self.save_checkpoint()

    def __len__(self) -> int:
        """Länge (nur für materialisierbare Datasets). Bei Streaming-Quellen
        wird TypeError geworfen (was list()/iter() tolerieren)."""
        try:
            n = len(self.dataset)  # type: ignore[arg-type]
        except TypeError:
            raise TypeError("Länge unbekannt für Streaming-Dataset")
        per_rank = sum(1 for i in range(n) if (i % self.world_size) == self.rank)
        batches = per_rank // self.batch_size
        if not self.drop_last and per_rank % self.batch_size:
            batches += 1
        return batches


class DistributedBatchLoader(BatchLoader):
    """Bequemkeits-Wrapper für verteiltes Sharding über mehrere GPUs/Nodes."""

    def __init__(
        self,
        dataset,
        batch_size: int = 8,
        rank: int = 0,
        world_size: int = 1,
        shuffle: bool = True,
        seed: int = 1337,
        **kwargs,
    ):
        super().__init__(
            dataset=dataset,
            batch_size=batch_size,
            shuffle=shuffle,
            rank=rank,
            world_size=world_size,
            seed=seed,
            **kwargs,
        )


# ---------------------------------------------------------------------- #
# Komfort-Funktion: Dateien -> tokenisierte Batches in einem Aufruf
# ---------------------------------------------------------------------- #


def build_training_loader(
    data_dir: str | Path,
    batch_size: int = 8,
    tokenize_fn: Optional[TokenizeFn] = None,
    text_field: str = "text",
    shuffle: bool = True,
    seed: int = 1337,
    rank: int = 0,
    world_size: int = 1,
    checkpoint_path: Optional[str | Path] = None,
) -> tuple[BatchLoader, PipelineStats]:
    """Rohdaten-Verzeichnis -> fertiger BatchLoader + Pipeline-Stats.

    Verwendet die Streaming-Pipeline, sodass beliebig große Verzeichnisse
    verarbeitet werden können. Die Stats werden beim Konsumieren befüllt.
    """
    files = list(iter_files(data_dir))

    def _doc_stream():
        for path in files:
            yield from read_file(path, text_field=text_field)

    pipeline = DataPipeline(tokenize_fn=tokenize_fn, text_field=text_field)
    examples, stats = pipeline.run(iter(_doc_stream()))
    loader = BatchLoader(
        list(examples) if False else examples,  # streaming: Generator
        batch_size=batch_size,
        shuffle=shuffle,
        seed=seed,
        rank=rank,
        world_size=world_size,
        checkpoint_path=checkpoint_path,
    )
    return loader, stats


# Bequemer Alias: "DataLoader" ist die öffentliche Bezeichnung des
# Batch-basierten Datenladens in der Shadow-Architektur.
DataLoader = BatchLoader
