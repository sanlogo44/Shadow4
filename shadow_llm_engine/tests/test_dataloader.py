"""Tests für den Shadow DataLoader (System 1): kleine Daten, große Daten,
Fehlerfälle, Streaming, Shuffle, Checkpoints, verteiltes Sharding."""

from __future__ import annotations

import csv
import json
import os
import tempfile

import pytest

pyarrow = pytest.importorskip("pyarrow")  # Parquet-Tests brauchen pyarrow
import pyarrow.parquet as pq
import pyarrow as pa

from shadow_engine.dataset.loader import (
    BatchLoader,
    DataPipeline,
    DistributedBatchLoader,
    Document,
    FORMAT_READERS,
    read_csv,
    read_file,
    read_json,
    read_jsonl,
    read_parquet,
    read_txt,
    iter_files,
    validate_document,
    build_training_loader,
)
from shadow_engine.dataset import LocalDirectorySource


# ---------------------------------------------------------------------- #
# Format-Reader
# ---------------------------------------------------------------------- #


def _make_data_dir(tmp_path):
    (tmp_path / "a.txt").write_text("Erster Absatz hier.\n\nZweiter Absatz hier.\n", encoding="utf-8")
    with open(tmp_path / "b.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"text": "hallo welt das ist ein test"}) + "\n")
        f.write(json.dumps({"text": "noch ein dokument zum testen"}) + "\n")
    with open(tmp_path / "c.json", "w", encoding="utf-8") as f:
        json.dump([{"text": "json array eins"}, {"text": "json array zwei"}], f)
    with open(tmp_path / "d.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["text", "label"])
        w.writeheader()
        w.writerow({"text": "csv zeile eins", "label": "a"})
        w.writerow({"text": "csv zeile zwei", "label": "b"})
    t = pa.table({"text": ["parquet eins hier", "parquet zwei hier"]})
    pq.write_table(t, str(tmp_path / "e.parquet"))


def test_all_format_readers(tmp_path):
    _make_data_dir(tmp_path)
    assert set(FORMAT_READERS) == {".txt", ".jsonl", ".json", ".csv", ".parquet"}
    assert len(list(read_txt(tmp_path / "a.txt"))) == 2
    assert len(list(read_jsonl(tmp_path / "b.jsonl"))) == 2
    assert len(list(read_json(tmp_path / "c.json"))) == 2
    assert len(list(read_csv(tmp_path / "d.csv"))) == 2
    assert len(list(read_parquet(tmp_path / "e.parquet"))) == 2


def test_iter_files_and_read_file_dispatch(tmp_path):
    _make_data_dir(tmp_path)
    files = sorted(p.name for p in iter_files(tmp_path))
    assert files == ["a.txt", "b.jsonl", "c.json", "d.csv", "e.parquet"]
    docs = []
    for p in iter_files(tmp_path):
        docs.extend(read_file(p))
    assert len(docs) == 10


def test_unsupported_format_raises(tmp_path):
    bad = tmp_path / "data.xyz"
    bad.write_text("noop")
    with pytest.raises(ValueError):
        list(read_file(bad))


def test_validate_document_drops_empty():
    assert validate_document(Document(text="   ")) is None
    assert validate_document(Document(text="ok")).text == "ok"


# ---------------------------------------------------------------------- #
# Pipeline
# ---------------------------------------------------------------------- #


def test_pipeline_cleaning_dedup_quality(tmp_path):
    _make_data_dir(tmp_path)
    docs = []
    for p in iter_files(tmp_path):
        docs.extend(read_file(p))
    pipe = DataPipeline(min_doc_length=10, tokenize_fn=lambda t: [ord(c) for c in t[:5]])
    examples, stats = pipe.run(iter(docs))
    examples = list(examples)
    assert stats.documents_in == 10
    assert stats.documents_after_tokenization == len(examples)
    assert all("input_ids" in e for e in examples)


def test_local_directory_source_supports_all_formats(tmp_path):
    _make_data_dir(tmp_path)
    src = LocalDirectorySource(tmp_path)
    docs = list(src.iter_documents())
    assert len(docs) == 10


# ---------------------------------------------------------------------- #
# BatchLoader: Shuffle, Batches, Checkpoints
# ---------------------------------------------------------------------- #


def test_batch_loader_batching_and_drop_last():
    data = [{"i": i} for i in range(10)]
    bl = BatchLoader(data, batch_size=3, shuffle=False, drop_last=True)
    batches = list(bl)
    assert len(batches) == 3  # 9/3, letzter (1 Element) verworfen
    assert all(len(b) == 3 for b in batches)


def test_batch_loader_shuffle_is_deterministic():
    data = [{"i": i} for i in range(20)]
    b1 = BatchLoader(data, batch_size=4, shuffle=True, seed=42)
    b2 = BatchLoader(data, batch_size=4, shuffle=True, seed=42)
    assert list(b1) == list(b2)


def test_batch_loader_shuffle_changes_order():
    data = [{"i": i} for i in range(50)]
    bl = BatchLoader(data, batch_size=5, shuffle=True, seed=7)
    flat = [e["i"] for batch in bl for e in batch]
    assert sorted(flat) == list(range(50))
    assert flat != list(range(50))  # tatsächlich gemischt


def test_batch_loader_checkpoint_save_and_resume(tmp_path):
    data = [{"i": i} for i in range(20)]
    cp = tmp_path / "cp.json"
    bl = BatchLoader(data, batch_size=4, shuffle=True, seed=1, checkpoint_path=cp)
    list(bl)
    assert cp.exists()
    assert bl.consumed == 20
    bl2 = BatchLoader(data, batch_size=4, shuffle=True, seed=1, checkpoint_path=cp)
    assert bl2.load_checkpoint() is True
    assert bl2.consumed == 20


# ---------------------------------------------------------------------- #
# Distributed Data Loading
# ---------------------------------------------------------------------- #


def test_distributed_sharding_covers_all_data():
    data = [{"i": i} for i in range(20)]
    seen = set()
    for rank in range(4):
        bl = DistributedBatchLoader(data, batch_size=2, rank=rank, world_size=4, shuffle=False)
        for batch in bl:
            for e in batch:
                seen.add(e["i"])
    assert seen == set(range(20))


def test_distributed_shards_are_disjoint():
    data = [{"i": i} for i in range(20)]
    ranks = []
    for rank in range(4):
        bl = DistributedBatchLoader(data, batch_size=2, rank=rank, world_size=4, shuffle=False)
        ranks.append({e["i"] for batch in bl for e in batch})
    # keine Überschneidung zwischen Ranks
    for a in range(4):
        for b in range(a + 1, 4):
            assert ranks[a].isdisjoint(ranks[b])


# ---------------------------------------------------------------------- #
# Große Daten (Streaming) + Fehlerfälle
# ---------------------------------------------------------------------- #


def test_large_streaming_does_not_materialize(tmp_path):
    """Streaming-Quelle (Generator) wird nicht vollständig in den Speicher geladen."""
    counter = {"n": 0}

    def gen():
        for i in range(10_000):
            counter["n"] += 1
            yield {"i": i}

    bl = BatchLoader(gen(), batch_size=32, shuffle=False)
    n_batches = 0
    for batch in bl:
        assert 1 <= len(batch) <= 32
        n_batches += 1
    assert n_batches == (10_000 + 31) // 32  # 313 Batches (letzter partial)


def test_pipeline_handles_malformed_jsonl(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"text": "gutes dokument hier"}\n{bad json}\n{"text": "noch gutes"}\n', encoding="utf-8")
    docs = list(read_jsonl(p))
    assert len(docs) == 2  # fehlerhafte Zeile übersprungen


def test_build_training_loader_end_to_end(tmp_path):
    _make_data_dir(tmp_path)
    loader, stats = build_training_loader(
        tmp_path, batch_size=2, tokenize_fn=lambda t: [ord(c) for c in t[:4]],
    )
    batches = list(loader)
    assert len(batches) >= 1
    assert all("input_ids" in e for batch in batches for e in batch)
