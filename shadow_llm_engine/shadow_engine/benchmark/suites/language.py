"""Sprache: Verständnis, Zusammenfassung, Übersetzung."""

from __future__ import annotations

from shadow_engine.benchmark.runner import BenchmarkCase, BenchmarkSuite


class LanguageSuite(BenchmarkSuite):
    name = "language"
    category = "language"

    def cases(self) -> list[BenchmarkCase]:
        return [
            BenchmarkCase(
                case_id="lang-comprehension-1",
                prompt=(
                    "Lies den folgenden Satz und beantworte die Frage.\n"
                    "Satz: 'Der Zug nach Hamburg fällt heute wegen einer Störung aus.'\n"
                    "Frage: Fährt der Zug heute? Antworte nur mit Ja oder Nein."
                ),
                check_fn=lambda out: "nein" in out.lower(),
                category="comprehension",
            ),
            BenchmarkCase(
                case_id="lang-summarization-1",
                prompt=(
                    "Fasse den folgenden Text in einem Satz zusammen:\n"
                    "'Die Photosynthese ist der Prozess, mit dem Pflanzen mithilfe von "
                    "Sonnenlicht, Wasser und Kohlendioxid Glukose und Sauerstoff produzieren.'"
                ),
                check_fn=lambda out: any(w in out.lower() for w in ["photosynthese", "sonnenlicht", "glukose"]),
                category="summarization",
            ),
            BenchmarkCase(
                case_id="lang-translation-1",
                prompt="Übersetze ins Englische: 'Guten Morgen, wie geht es dir?'",
                check_fn=lambda out: "good morning" in out.lower(),
                category="translation",
            ),
        ]
