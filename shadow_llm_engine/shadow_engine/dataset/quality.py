"""
Heuristische Qualitätsprüfung für Trainingsdokumente.

Bewusst einfach & transparent gehalten (keine externen ML-Klassifizierer),
damit die Regeln nachvollziehbar und ohne zusätzliche Abhängigkeiten
einsetzbar sind. Kann später durch einen gelernten Qualitäts-Klassifizierer
ersetzt/ergänzt werden, ohne die Pipeline-Schnittstelle zu ändern.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WORD = re.compile(r"\w+", re.UNICODE)
_ALPHA = re.compile(r"[^\W\d_]", re.UNICODE)


@dataclass
class QualityReport:
    score: float
    passed: bool
    reasons: list[str] = field(default_factory=list)


class QualityFilter:
    def __init__(
        self,
        min_doc_length: int = 20,
        max_doc_length: int = 200_000,
        min_alpha_ratio: float = 0.6,
        max_symbol_ratio: float = 0.3,
        quality_threshold: float = 0.5,
    ):
        self.min_doc_length = min_doc_length
        self.max_doc_length = max_doc_length
        self.min_alpha_ratio = min_alpha_ratio
        self.max_symbol_ratio = max_symbol_ratio
        self.quality_threshold = quality_threshold

    def score(self, text: str) -> QualityReport:
        reasons = []
        length = len(text)
        words = _WORD.findall(text)
        alpha_chars = len(_ALPHA.findall(text))

        checks = []

        if length < self.min_doc_length:
            reasons.append(f"zu kurz ({length} < {self.min_doc_length})")
            checks.append(0.0)
        elif length > self.max_doc_length:
            reasons.append(f"zu lang ({length} > {self.max_doc_length})")
            checks.append(0.3)
        else:
            checks.append(1.0)

        if not words:
            reasons.append("keine Wörter erkannt")
            checks.append(0.0)
        else:
            avg_word_len = sum(len(w) for w in words) / len(words)
            if avg_word_len < 1.5 or avg_word_len > 20:
                reasons.append(f"unrealistische mittlere Wortlänge ({avg_word_len:.1f})")
                checks.append(0.2)
            else:
                checks.append(1.0)

        alpha_ratio = alpha_chars / max(length, 1)
        if alpha_ratio < self.min_alpha_ratio:
            reasons.append(f"geringer Buchstabenanteil ({alpha_ratio:.2f})")
            checks.append(alpha_ratio / self.min_alpha_ratio)
        else:
            checks.append(1.0)

        unique_word_ratio = len(set(words)) / max(len(words), 1)
        if unique_word_ratio < 0.3:
            reasons.append(f"sehr repetitiv (unique-ratio={unique_word_ratio:.2f})")
            checks.append(unique_word_ratio / 0.3)
        else:
            checks.append(1.0)

        final_score = sum(checks) / len(checks)
        passed = final_score >= self.quality_threshold and length >= self.min_doc_length
        return QualityReport(score=final_score, passed=passed, reasons=reasons)

    def filter(self, docs):
        for doc in docs:
            report = self.score(doc)
            if report.passed:
                yield doc
