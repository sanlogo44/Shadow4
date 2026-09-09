from shadow_engine.dataset import DatasetManager, LocalDirectorySource, Deduplicator, normalize_text
from shadow_engine.config import DatasetConfig


def test_normalize_text_strips_html_and_control_chars():
    dirty = "<p>Hallo   Welt!!!!!!!!!!!!</p>\x00"
    clean = normalize_text(dirty)
    assert "<p>" not in clean
    assert "\x00" not in clean
    assert "Hallo Welt" in clean


def test_deduplicator_detects_exact_duplicate():
    dedup = Deduplicator(method="exact")
    assert dedup.is_duplicate("gleicher text") is False
    assert dedup.is_duplicate("gleicher text") is True


def test_pipeline_end_to_end(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "a.txt").write_text("Dies ist ein ausreichend langer Beispieltext für Shadow.", encoding="utf-8")
    (raw_dir / "b.txt").write_text("kurz", encoding="utf-8")  # sollte durch Qualitätsfilter fallen

    cfg = DatasetConfig(clean_dir=str(tmp_path / "clean"), min_doc_length=20)
    manager = DatasetManager(cfg)
    stats = manager.run_pipeline([LocalDirectorySource(raw_dir)])

    assert stats.documents_in == 2
    assert stats.documents_after_quality == 1

    docs = list(manager.iter_clean_documents())
    assert len(docs) == 1
    assert "Shadow" in docs[0]
