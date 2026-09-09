from shadow_engine.tokenizer import ShadowTokenizer
from shadow_engine.config import TokenizerConfig


def test_tokenizer_roundtrip():
    tok = ShadowTokenizer(TokenizerConfig(vocab_size=300))
    corpus = [
        "Hallo Welt, dies ist ein Test.",
        "Shadow ist eine eigene KI-Engine.",
        "Mehrsprachigkeit: Hello world, this is a test.",
    ]
    tok.train(corpus)

    text = "Hallo Shadow!"
    ids = tok.encode(text)
    decoded = tok.decode(ids)
    assert isinstance(ids, list) and all(isinstance(i, int) for i in ids)
    assert "Hallo" in decoded and "Shadow" in decoded


def test_tokenizer_save_load(tmp_path):
    tok = ShadowTokenizer(TokenizerConfig(vocab_size=280))
    tok.train(["ein kleiner Testkorpus für Shadow"])
    path = tmp_path / "tok.json"
    tok.save(path)

    loaded = ShadowTokenizer.load(path)
    ids_original = tok.encode("Test")
    ids_loaded = loaded.encode("Test")
    assert ids_original == ids_loaded
