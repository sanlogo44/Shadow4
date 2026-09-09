"""
Eigener Byte-Level BPE Tokenizer fuer Shadow.

Byte-Level heisst: jedes Unicode-Zeichen wird zuerst in UTF-8-Bytes zerlegt.
Dadurch kann der Tokenizer JEDEN Text jeder Sprache verlustfrei kodieren,
ohne <unk>-Token -- eine Grundvoraussetzung fuer "eigene Sprache" und
"mehrere Sprachen" aus der Spezifikation.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Optional

from shadow_engine.config import TokenizerConfig

_BYTE_PATTERN = re.compile(
    r"""'s|'t|'re|'ve|'m|'ll|'d| ?\p{L}+| ?\p{N}+| ?[^\s\p{L}\p{N}]+|\s+(?!\S)|\s+""",
    re.UNICODE,
) if False else re.compile(
    r"""'s|'t|'re|'ve|'m|'ll|'d| ?[^\W\d_]+| ?\d+| ?[^\s\w]+|\s+(?!\S)|\s+""",
    re.UNICODE,
)


def _bytes_to_unicode() -> dict[int, str]:
    """Reversible Abbildung Byte(0-255) -> druckbares Unicode-Zeichen (wie bei GPT-2)."""
    bs = list(range(ord("!"), ord("~") + 1)) + list(range(ord("\xa1"), ord("\xac") + 1)) + \
         list(range(ord("\xae"), ord("\xff") + 1))
    cs = bs[:]
    n = 0
    for b in range(256):
        if b not in bs:
            bs.append(b)
            cs.append(256 + n)
            n += 1
    return {b: chr(c) for b, c in zip(bs, cs)}


class ShadowTokenizer:
    """
    Byte-Level BPE Tokenizer.

    Nutzung:
        tok = ShadowTokenizer(config)
        tok.train(corpus_iterator)
        ids = tok.encode("Hallo Welt")
        text = tok.decode(ids)
        tok.save("tokenizer.json")
        tok2 = ShadowTokenizer.load("tokenizer.json")
    """

    def __init__(self, config: Optional[TokenizerConfig] = None):
        self.config = config or TokenizerConfig()
        self._byte_encoder = _bytes_to_unicode()
        self._byte_decoder = {v: k for k, v in self._byte_encoder.items()}

        self.special_tokens: list[str] = list(self.config.special_tokens)
        self.vocab: dict[str, int] = {}
        self.merges: dict[tuple[str, str], int] = {}
        self._merge_order: list[tuple[str, str]] = []

        self._init_base_vocab()

    # ------------------------------------------------------------------ #
    # Vokabular-Aufbau
    # ------------------------------------------------------------------ #
    def _init_base_vocab(self):
        self.vocab = {}
        for i, tok in enumerate(self.special_tokens):
            self.vocab[tok] = i
        offset = len(self.special_tokens)
        for i in range(256):
            ch = self._byte_encoder[i]
            if ch not in self.vocab:
                self.vocab[ch] = offset
                offset += 1

    @property
    def vocab_size(self) -> int:
        return len(self.vocab)

    def _pre_tokenize(self, text: str) -> list[str]:
        return _BYTE_PATTERN.findall(text)

    def _to_byte_symbols(self, token: str) -> tuple[str, ...]:
        b = token.encode("utf-8")
        return tuple(self._byte_encoder[byte] for byte in b)

    # ------------------------------------------------------------------ #
    # Training (BPE)
    # ------------------------------------------------------------------ #
    def train(self, corpus: Iterable[str], vocab_size: Optional[int] = None, verbose: bool = False):
        """Trainiert das BPE-Vokabular auf einem Text-Korpus (Iterator von Strings)."""
        target_vocab_size = vocab_size or self.config.vocab_size
        self._init_base_vocab()
        self._merge_order = []

        word_freqs: Counter[tuple[str, ...]] = Counter()
        for line in corpus:
            for chunk in self._pre_tokenize(line):
                symbols = self._to_byte_symbols(chunk)
                word_freqs[symbols] += 1

        splits = {word: list(word) for word in word_freqs}

        num_merges_needed = max(0, target_vocab_size - len(self.vocab))
        for step in range(num_merges_needed):
            pair_counts: Counter[tuple[str, str]] = Counter()
            for word, freq in word_freqs.items():
                symbols = splits[word]
                for i in range(len(symbols) - 1):
                    pair_counts[(symbols[i], symbols[i + 1])] += freq

            if not pair_counts:
                break

            best_pair, _ = pair_counts.most_common(1)[0]
            new_token = "".join(best_pair)
            new_id = len(self.vocab)
            self.vocab[new_token] = new_id
            self.merges[best_pair] = new_id
            self._merge_order.append(best_pair)

            for word in list(splits.keys()):
                symbols = splits[word]
                merged = []
                i = 0
                while i < len(symbols):
                    if i < len(symbols) - 1 and (symbols[i], symbols[i + 1]) == best_pair:
                        merged.append(new_token)
                        i += 2
                    else:
                        merged.append(symbols[i])
                        i += 1
                splits[word] = merged

            if verbose and step % 500 == 0:
                print(f"[ShadowTokenizer] merge {step}/{num_merges_needed}: {best_pair} -> {new_token}")

        return self

    # ------------------------------------------------------------------ #
    # Encoding / Decoding
    # ------------------------------------------------------------------ #
    def _bpe_word(self, symbols: list[str]) -> list[str]:
        while len(symbols) > 1:
            pairs = [(symbols[i], symbols[i + 1]) for i in range(len(symbols) - 1)]
            ranked = [(self.merges[p], p) for p in pairs if p in self.merges]
            if not ranked:
                break
            _, best_pair = min(ranked, key=lambda x: x[0])
            merged = []
            i = 0
            while i < len(symbols):
                if i < len(symbols) - 1 and (symbols[i], symbols[i + 1]) == best_pair:
                    merged.append("".join(best_pair))
                    i += 2
                else:
                    merged.append(symbols[i])
                    i += 1
            symbols = merged
        return symbols

    def encode(self, text: str, add_special_tokens: bool = True) -> list[int]:
        ids: list[int] = []
        if add_special_tokens and "<bos>" in self.vocab:
            ids.append(self.vocab["<bos>"])

        for chunk in self._pre_tokenize(text):
            symbols = list(self._to_byte_symbols(chunk))
            for tok in self._bpe_word(symbols):
                ids.append(self.vocab.get(tok, self.vocab.get("<unk>", 0)))

        if add_special_tokens and "<eos>" in self.vocab:
            ids.append(self.vocab["<eos>"])
        return ids

    def decode(self, ids: list[int], skip_special_tokens: bool = True) -> str:
        inv_vocab = {v: k for k, v in self.vocab.items()}
        chars: list[str] = []
        for i in ids:
            tok = inv_vocab.get(i, "")
            if skip_special_tokens and tok in self.special_tokens:
                continue
            chars.append(tok)
        byte_str = "".join(chars)
        byte_values = bytes(self._byte_decoder.get(c, 0) for c in byte_str)
        return byte_values.decode("utf-8", errors="replace")

    # ------------------------------------------------------------------ #
    # Persistenz
    # ------------------------------------------------------------------ #
    def save(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "config": self.config.__dict__,
            "vocab": self.vocab,
            "merges": [list(p) for p in self._merge_order],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "ShadowTokenizer":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cfg = TokenizerConfig(**data["config"])
        tok = cls(cfg)
        tok.vocab = data["vocab"]
        tok._merge_order = [tuple(p) for p in data["merges"]]
        tok.merges = {pair: tok.vocab["".join(pair)] for pair in tok._merge_order if "".join(pair) in tok.vocab}
        return tok
