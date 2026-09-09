"""
Reinigungs- und Duplikat-Erkennungsfunktionen für die Datenpipeline.

    Datenquelle -> Reinigung -> Qualitätsprüfung -> Tokenizer -> Trainingsdaten
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable, Iterator

_MULTI_WHITESPACE = re.compile(r"\s+")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HTML_TAG = re.compile(r"<[^>]+>")
_REPEATED_CHAR = re.compile(r"(.)\1{6,}")  # z. B. "!!!!!!!!!!" oder "aaaaaaaaaa"


def normalize_text(text: str) -> str:
    """Unicode-Normalisierung, HTML-Tags und Steuerzeichen entfernen, Whitespace glätten."""
    text = unicodedata.normalize("NFKC", text)
    text = _HTML_TAG.sub(" ", text)
    text = _CONTROL_CHARS.sub("", text)
    text = _REPEATED_CHAR.sub(lambda m: m.group(1) * 3, text)
    text = _MULTI_WHITESPACE.sub(" ", text).strip()
    return text


def clean_documents(docs: Iterable[str]) -> Iterator[str]:
    for doc in docs:
        cleaned = normalize_text(doc)
        if cleaned:
            yield cleaned


# ---------------------------------------------------------------------- #
# Duplikat-Erkennung
# ---------------------------------------------------------------------- #

def exact_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _shingles(text: str, k: int = 5) -> set[str]:
    words = text.split()
    if len(words) < k:
        return {" ".join(words)}
    return {" ".join(words[i:i + k]) for i in range(len(words) - k + 1)}


def simhash(text: str, num_bits: int = 64) -> int:
    """
    Einfache SimHash-Implementierung für nahezu-Duplikat-Erkennung.
    Zwei Texte mit kleiner Hamming-Distanz zwischen ihren SimHashes
    sind sich inhaltlich sehr ähnlich.
    """
    v = [0] * num_bits
    for shingle in _shingles(text):
        h = int(hashlib.md5(shingle.encode("utf-8")).hexdigest(), 16)
        for i in range(num_bits):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1
    fingerprint = 0
    for i in range(num_bits):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint


def hamming_distance(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


class Deduplicator:
    """
    Entfernt exakte und (optional) nahezu-Duplikate aus einem Dokumentstrom.

    method: "exact" | "simhash"
    """

    def __init__(self, method: str = "simhash", simhash_threshold: int = 6):
        self.method = method
        self.simhash_threshold = simhash_threshold
        self._exact_hashes: set[str] = set()
        self._simhashes: list[int] = []

    def is_duplicate(self, text: str) -> bool:
        h = exact_hash(text)
        if h in self._exact_hashes:
            return True

        if self.method == "simhash":
            sh = simhash(text)
            for existing in self._simhashes:
                if hamming_distance(sh, existing) <= self.simhash_threshold:
                    return True
            self._simhashes.append(sh)

        self._exact_hashes.add(h)
        return False

    def deduplicate(self, docs: Iterable[str]) -> Iterator[str]:
        for doc in docs:
            if not self.is_duplicate(doc):
                yield doc
