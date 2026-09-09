"""
Schwarm (Swarm): erzeugt mehrere Agenten für eine gemeinsame Aufgabe
und führt deren Ergebnisse zusammen.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from shadow_engine.agents.agent import Agent, Task, TaskStatus, PlanFn, ExecuteFn

# Signatur: (Liste von Task-Ergebnissen) -> zusammengeführtes Ergebnis
MergeFn = Callable[[list[Task]], str]


def default_merge(tasks: list[Task]) -> str:
    """Standard-Merge: nummerierte Zusammenfassung aller erfolgreichen Teilergebnisse."""
    lines = []
    for i, t in enumerate(tasks, start=1):
        if t.status == TaskStatus.DONE and t.result:
            lines.append(f"[Agent {i}] {t.result}")
        elif t.status == TaskStatus.FAILED:
            lines.append(f"[Agent {i}] FEHLGESCHLAGEN: {t.error}")
    return "\n".join(lines)


@dataclass
class SwarmResult:
    swarm_id: str
    subtasks: list[Task] = field(default_factory=list)
    merged_result: str = ""


class Swarm:
    """
    Erzeugt `num_agents` Agenten mit denselben plan_fn/execute_fn-Callbacks
    und lässt sie dieselbe (oder je Agent leicht variierte) Aufgabe
    parallel bzw. sequentiell bearbeiten. Ergebnisse werden über
    `merge_fn` zusammengeführt.
    """

    def __init__(
        self,
        plan_fn: PlanFn,
        execute_fn: ExecuteFn,
        merge_fn: Optional[MergeFn] = None,
        swarm_id: Optional[str] = None,
    ):
        self.plan_fn = plan_fn
        self.execute_fn = execute_fn
        self.merge_fn = merge_fn or default_merge
        self.swarm_id = swarm_id or str(uuid.uuid4())
        self.agents: list[Agent] = []

    def spawn(self, num_agents: int, name_prefix: str = "agent") -> list[Agent]:
        self.agents = [
            Agent(name=f"{name_prefix}-{i}", plan_fn=self.plan_fn, execute_fn=self.execute_fn)
            for i in range(num_agents)
        ]
        return self.agents

    def dispatch(
        self,
        descriptions: list[str],
        context: Optional[dict] = None,
    ) -> SwarmResult:
        """
        Verteilt eine Liste von (Teil-)Aufgabenbeschreibungen auf die
        gespawnten Agenten (round-robin, falls mehr Aufgaben als Agenten)
        und führt die Ergebnisse zusammen.
        """
        if not self.agents:
            self.spawn(max(1, len(descriptions)))

        results: list[Task] = []
        for i, desc in enumerate(descriptions):
            agent = self.agents[i % len(self.agents)]
            results.append(agent.handle(desc, context))

        merged = self.merge_fn(results)
        return SwarmResult(swarm_id=self.swarm_id, subtasks=results, merged_result=merged)
