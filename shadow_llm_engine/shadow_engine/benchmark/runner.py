"""
Benchmark-System (Admin-only).

Testbereiche: Sprache, Logik, Programmierung, Leistung.
Ergebnisse werden versioniert (pro Modell-Version aus der Model Registry)
und sind über verschiedene Läufe hinweg vergleichbar.

Zugriffsschutz: `BenchmarkRunner.run()` verlangt ein `AdminContext`.
Die tatsächliche Authentifizierung (wer ist Admin) erfolgt in der API-
Schicht (siehe api/server.py); der Runner selbst prüft nur, dass ein
gültiger Kontext übergeben wurde, um versehentliche Aufrufe ohne
Admin-Rechte zu verhindern.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional


class NotAuthorizedError(Exception):
    pass


@dataclass
class AdminContext:
    admin_id: str
    is_admin: bool = True

    def require_admin(self):
        if not self.is_admin:
            raise NotAuthorizedError("Benchmark-Ausführung erfordert Admin-Rechte.")


@dataclass
class BenchmarkCase:
    case_id: str
    prompt: str
    check_fn: Callable[[str], bool]
    category: str
    weight: float = 1.0


@dataclass
class BenchmarkCaseResult:
    case_id: str
    category: str
    passed: bool
    latency_ms: float
    output: str = ""


@dataclass
class BenchmarkSuiteResult:
    suite_name: str
    category: str
    score: float
    total_cases: int
    passed_cases: int
    case_results: list[BenchmarkCaseResult] = field(default_factory=list)
    avg_latency_ms: float = 0.0


class BenchmarkSuite:
    """Basisklasse für eine Testkategorie (Sprache, Logik, Programmierung, Leistung)."""

    name: str = "base"
    category: str = "base"

    def cases(self) -> list[BenchmarkCase]:
        raise NotImplementedError

    def run(self, generate_fn: Callable[[str], str]) -> BenchmarkSuiteResult:
        results = []
        latencies = []
        for case in self.cases():
            start = time.perf_counter()
            output = generate_fn(case.prompt)
            latency_ms = (time.perf_counter() - start) * 1000
            latencies.append(latency_ms)
            passed = case.check_fn(output)
            results.append(BenchmarkCaseResult(
                case_id=case.case_id, category=case.category,
                passed=passed, latency_ms=latency_ms, output=output[:500],
            ))

        total = len(results)
        passed_count = sum(1 for r in results if r.passed)
        score = passed_count / total if total else 0.0
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0

        return BenchmarkSuiteResult(
            suite_name=self.name, category=self.category, score=score,
            total_cases=total, passed_cases=passed_count,
            case_results=results, avg_latency_ms=avg_latency,
        )


@dataclass
class BenchmarkReport:
    run_id: str
    model_namespace: str
    model_version: str
    created_at: str
    suite_results: list[BenchmarkSuiteResult]
    overall_score: float

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "model_namespace": self.model_namespace,
            "model_version": self.model_version,
            "created_at": self.created_at,
            "overall_score": self.overall_score,
            "suites": [
                {
                    "suite_name": s.suite_name,
                    "category": s.category,
                    "score": s.score,
                    "total_cases": s.total_cases,
                    "passed_cases": s.passed_cases,
                    "avg_latency_ms": s.avg_latency_ms,
                }
                for s in self.suite_results
            ],
        }


class BenchmarkRunner:
    """
    Führt eine Reihe von BenchmarkSuites gegen ein Modell aus und
    persistiert die Ergebnisse versioniert unter `results_dir`.
    """

    def __init__(self, suites: list[BenchmarkSuite], results_dir: str | Path = "./benchmark_results"):
        self.suites = suites
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)

    def run(
        self,
        admin_context: AdminContext,
        generate_fn: Callable[[str], str],
        model_namespace: str,
        model_version: str,
        categories: Optional[list[str]] = None,
    ) -> BenchmarkReport:
        admin_context.require_admin()

        suite_results = []
        for suite in self.suites:
            if categories and suite.category not in categories:
                continue
            suite_results.append(suite.run(generate_fn))

        overall = (
            sum(r.score for r in suite_results) / len(suite_results)
            if suite_results else 0.0
        )

        report = BenchmarkReport(
            run_id=f"{model_namespace}-{model_version}-{int(time.time())}",
            model_namespace=model_namespace,
            model_version=model_version,
            created_at=datetime.now(timezone.utc).isoformat(),
            suite_results=suite_results,
            overall_score=overall,
        )
        self._persist(report)
        return report

    def _persist(self, report: BenchmarkReport):
        ns_dir = self.results_dir / report.model_namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        path = ns_dir / f"{report.model_version}__{report.run_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def history(self, model_namespace: str) -> list[dict]:
        ns_dir = self.results_dir / model_namespace
        if not ns_dir.exists():
            return []
        reports = []
        for path in sorted(ns_dir.glob("*.json")):
            reports.append(json.loads(path.read_text(encoding="utf-8")))
        return reports

    def compare_versions(self, model_namespace: str, version_a: str, version_b: str) -> dict:
        history = self.history(model_namespace)
        latest_a = next((r for r in reversed(history) if r["model_version"] == version_a), None)
        latest_b = next((r for r in reversed(history) if r["model_version"] == version_b), None)
        if not latest_a or not latest_b:
            raise ValueError("Für eine der Versionen liegt kein Benchmark-Ergebnis vor.")
        return {
            "version_a": version_a, "version_b": version_b,
            "overall_score_a": latest_a["overall_score"],
            "overall_score_b": latest_b["overall_score"],
            "delta": latest_b["overall_score"] - latest_a["overall_score"],
        }
