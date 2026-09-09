from shadow_engine.benchmark.suites.language import LanguageSuite
from shadow_engine.benchmark.suites.logic import LogicSuite
from shadow_engine.benchmark.suites.coding import CodingSuite
from shadow_engine.benchmark.suites.performance import PerformanceSuite

DEFAULT_SUITES = [LanguageSuite(), LogicSuite(), CodingSuite(), PerformanceSuite()]

__all__ = ["LanguageSuite", "LogicSuite", "CodingSuite", "PerformanceSuite", "DEFAULT_SUITES"]
