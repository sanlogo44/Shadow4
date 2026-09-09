"""Logik: Problemlösung, Schlussfolgerungen."""

from __future__ import annotations

from shadow_engine.benchmark.runner import BenchmarkCase, BenchmarkSuite


class LogicSuite(BenchmarkSuite):
    name = "logic"
    category = "logic"

    def cases(self) -> list[BenchmarkCase]:
        return [
            BenchmarkCase(
                case_id="logic-arithmetic-1",
                prompt="Was ist 17 * 6? Antworte nur mit der Zahl.",
                check_fn=lambda out: "102" in out,
                category="problem_solving",
            ),
            BenchmarkCase(
                case_id="logic-syllogism-1",
                prompt=(
                    "Alle Vögel können fliegen. Ein Pinguin ist ein Vogel. "
                    "Stimmt die Aussage 'Ein Pinguin kann fliegen' laut dieser Logik? "
                    "Antworte mit Ja oder Nein."
                ),
                check_fn=lambda out: "ja" in out.lower(),
                category="reasoning",
            ),
            BenchmarkCase(
                case_id="logic-sequence-1",
                prompt="Setze die Zahlenreihe fort: 2, 4, 8, 16, __",
                check_fn=lambda out: "32" in out,
                category="reasoning",
            ),
        ]
