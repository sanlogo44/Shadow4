"""
Leistung: Geschwindigkeit, Speicherverbrauch.

Diese Suite unterscheidet sich von den anderen: statt inhaltlicher
Korrektheit werden reine Laufzeit- und Speichermetriken erfasst. Ein
`generate_fn` wird mehrfach aufgerufen; die `check_fn` prüft lediglich,
dass überhaupt eine Ausgabe erzeugt wurde -- die eigentliche Auswertung
erfolgt über `latency_ms` im Ergebnis sowie den zusätzlichen
`memory_report`.
"""

from __future__ import annotations

import os

from shadow_engine.benchmark.runner import BenchmarkCase, BenchmarkSuite


def _current_memory_mb() -> float:
    try:
        import resource
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    except ImportError:
        return -1.0


class PerformanceSuite(BenchmarkSuite):
    name = "performance"
    category = "performance"

    def __init__(self, prompt_lengths: tuple[int, ...] = (16, 128, 512)):
        self.prompt_lengths = prompt_lengths

    def cases(self) -> list[BenchmarkCase]:
        cases = []
        for length in self.prompt_lengths:
            prompt = ("Wiederhole das Wort Shadow. " * (length // 4 + 1))[: length * 5]
            cases.append(BenchmarkCase(
                case_id=f"perf-latency-{length}",
                prompt=prompt,
                check_fn=lambda out: len(out) > 0,
                category="speed",
            ))
        return cases

    def run(self, generate_fn):
        result = super().run(generate_fn)
        result.case_results = [
            r for r in result.case_results
        ]
        # Speichernutzung als zusätzliche Information anhängen
        mem_mb = _current_memory_mb()
        for r in result.case_results:
            r.output = f"{r.output} [peak_rss_mb={mem_mb:.1f}]" if mem_mb >= 0 else r.output
        return result
