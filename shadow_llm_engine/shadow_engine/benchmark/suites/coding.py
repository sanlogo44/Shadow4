"""Programmierung: Code erstellen, Fehler finden."""

from __future__ import annotations

from shadow_engine.benchmark.runner import BenchmarkCase, BenchmarkSuite


class CodingSuite(BenchmarkSuite):
    name = "coding"
    category = "coding"

    def cases(self) -> list[BenchmarkCase]:
        return [
            BenchmarkCase(
                case_id="code-gen-1",
                prompt="Schreibe eine Python-Funktion `add(a, b)`, die die Summe zweier Zahlen zurückgibt.",
                check_fn=lambda out: "def add" in out and "return" in out,
                category="code_generation",
            ),
            BenchmarkCase(
                case_id="code-bugfix-1",
                prompt=(
                    "Finde den Fehler in dieser Funktion und korrigiere ihn:\n"
                    "def multiply(a, b):\n    return a + b"
                ),
                check_fn=lambda out: "a * b" in out.replace(" ", "").replace("a*b", "a * b") or "a*b" in out.replace(" ", ""),
                category="bug_finding",
            ),
        ]
