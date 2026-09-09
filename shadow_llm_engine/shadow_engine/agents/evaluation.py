"""
Ergebnisbewertung für Shadow-Agenten.

Ein `ResultEvaluator` prüft, ob das Ergebnis einer Aufgabe qualitativ
ausreichend ist (z. B. nicht-leer, enthält Schlüsselwörter, erfüllt
eine benutzerdefinierte Prädikat-Funktion). Damit kann ein Agent
eigene Ergebnisse bewerten und bei Bedarf nachbessern.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


# (result, task_description, context) -> (passed: bool, feedback: str|None)
EvaluatorFn = Callable[[str, str, dict], tuple[bool, Optional[str]]]


@dataclass
class EvaluationResult:
    passed: bool
    feedback: Optional[str] = None
    reasons: list[str] = field(default_factory=list)


class ResultEvaluator:
    """Standard-Evaluatoren + Plugin für benutzerdefinierte Prädikate."""

    def __init__(self, min_length: int = 1, contains: Optional[list[str]] = None,
                 predicate: Optional[EvaluatorFn] = None):
        self.min_length = min_length
        self.contains = contains or []
        self.predicate = predicate

    def evaluate(self, result: str, task_description: str, context: Optional[dict] = None) -> EvaluationResult:
        context = context or {}
        reasons: list[str] = []

        if result is None:
            return EvaluationResult(False, "Ergebnis ist None", ["none"])
        if len(str(result).strip()) < self.min_length:
            reasons.append("zu kurz")

        for keyword in self.contains:
            if keyword.lower() not in str(result).lower():
                reasons.append(f"fehlt: {keyword}")

        passed_default = not reasons
        feedback: Optional[str] = None
        if self.predicate is not None:
            try:
                pred_passed, pred_feedback = self.predicate(result, task_description, context)
                if not pred_passed:
                    passed_default = False
                    feedback = pred_feedback
            except Exception as e:
                passed_default = False
                feedback = f"Prädikat-Fehler: {e}"

        return EvaluationResult(passed=passed_default, feedback=feedback or (None if passed_default else "; ".join(reasons)), reasons=reasons)
