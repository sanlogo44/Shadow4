"""
Schwarm (Swarm): erzeugt mehrere Agenten für eine gemeinsame Aufgabe
und führt deren Ergebnisse zusammen.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from shadow_engine.agents.agent import Agent, Task, TaskStatus, PlanFn, ExecuteFn
from shadow_engine.agents.memory import AgentMemory

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


# ---------------------------------------------------------------------- #
# MessageBus: Inter-Agent-Kommunikation
# ---------------------------------------------------------------------- #


class MessageBus:
    """Asynchrone Nachrichten-Queue zwischen Agenten (Publisher/Subscriber).

    Agenten können Ergebnisse, Teilergebnisse und Anfragen an andere Agenten
    weiterleiten -- die Schwarm-Koordination (z. B. Research -> Coding)
    läuft über diesen Bus.
    """

    def __init__(self):
        self._queues: dict[str, list] = {}
        self._lock = threading.Lock()

    def subscribe(self, agent_name: str) -> None:
        with self._lock:
            if agent_name not in self._queues:
                self._queues[agent_name] = []

    def publish(self, target: str, message: dict) -> bool:
        with self._lock:
            if target not in self._queues:
                return False
            self._queues[target].append(message)
            return True

    def drain(self, agent_name: str) -> list[dict]:
        with self._lock:
            q = self._queues.get(agent_name, [])
            msgs = list(q)
            q.clear()
            return msgs


# ---------------------------------------------------------------------- #
# SwarmAgent: rollenbasierte Unteragenten (Research/Coding/Testing/Review)
# ---------------------------------------------------------------------- #


@dataclass
class RoleAgent:
    """Ein Agent mit einer festen Rolle im Schwarm."""
    name: str
    role: str
    agent: Agent


# Rollen-Definitionen für den Standard-Schwarm
SWARM_ROLES = {
    "research": "Analysiert Anforderung, sammelt Informationen.",
    "coding": "Implementiert Lösung aus den Erkenntnissen des Research-Agenten.",
    "testing": "Prüft die Lösung auf Korrektheit.",
    "review": "Bewertet Endqualität und gibt Feedback.",
}


class SwarmAgent:
    """
    Schwarm-Agent mit rollenbasierten Unteragenten und MessageBus.

    Ablauf (zielorientiert):
        goal -> Analyse -> Aufgaben erstellen -> Agenten starten
             -> Ergebnisse prüfen -> Ziel erreicht?
        Falls nein: neue Aufgaben erzeugen (iterativ).

    Die Rollenverteilung (Research/Coding/Testing/Review) erfolgt über
    separate Agenten, die über den MessageBus kommunizieren. Jede Rolle
    erhält eigene plan_fn/execute_fn (typischerweise Shadow LLM API-Aufrufe).
    """

    def __init__(
        self,
        plan_fns: dict[str, PlanFn],
        execute_fns: dict[str, ExecuteFn],
        roles: Optional[list[str]] = None,
        master_name: str = "master",
        max_iterations: int = 10,
        merge_fn: Optional[MergeFn] = None,
    ):
        self.roles = roles or list(SWARM_ROLES.keys())
        self.plan_fns = plan_fns
        self.execute_fns = execute_fns
        self.master_name = master_name
        self.max_iterations = max_iterations
        self.merge_fn = merge_fn or default_merge
        self.bus = MessageBus()
        self.sub_agents: dict[str, RoleAgent] = {}
        self._spawn()

    def _spawn(self) -> None:
        for role in self.roles:
            plan_fn = self.plan_fns.get(role) or self.plan_fns.get("default")
            execute_fn = self.execute_fns.get(role) or self.execute_fns.get("default")
            if plan_fn is None or execute_fn is None:
                continue
            agent = Agent(name=f"{role}-agent", plan_fn=plan_fn, execute_fn=execute_fn)
            self.bus.subscribe(agent.name)
            self.sub_agents[role] = RoleAgent(name=agent.name, role=role, agent=agent)

    def dispatch(self, descriptions: list[str], context: Optional[dict] = None) -> SwarmResult:
        """Verteilt Aufgaben auf die rollenbasierten Agenten (round-robin)."""
        context = context or {}
        results: list[Task] = []
        agents = list(self.sub_agents.values())
        if not agents:
            return SwarmResult(swarm_id=str(uuid.uuid4()), subtasks=results, merged_result="")
        for i, desc in enumerate(descriptions):
            ra = agents[i % len(agents)]
            # Vorgänger-Ergebnis an den nächsten Agenten weiterleiten (Pipeline)
            if results:
                self.bus.publish(ra.name, {"from": results[-1].description, "result": results[-1].result})
            task = ra.agent.handle(desc, context)
            results.append(task)
        merged = self.merge_fn(results)
        return SwarmResult(swarm_id=str(uuid.uuid4()), subtasks=results, merged_result=merged)

    def pursue_goal(self, goal: str, context: Optional[dict] = None,
                    goal_evaluator: Optional[Callable[[str, list[str]], tuple[bool, Optional[str]]]] = None) -> SwarmResult:
        """Iterativer Ziel-Loop: erstellt neue Aufgaben, bis das Ziel erreicht ist."""
        context = context or {}
        all_results: list[str] = []
        all_tasks: list[Task] = []
        current_desc: Optional[str] = goal
        iterations = 0
        while current_desc and iterations < self.max_iterations:
            iterations += 1
            result = self.dispatch([current_desc], context)
            all_tasks.extend(result.subtasks)
            all_results.append(result.merged_result)
            if goal_evaluator:
                achieved, next_desc = goal_evaluator(goal, all_results)
                if achieved:
                    break
                current_desc = next_desc
            else:
                break
        return SwarmResult(swarm_id=str(uuid.uuid4()), subtasks=all_tasks,
                           merged_result=default_merge(all_tasks))
