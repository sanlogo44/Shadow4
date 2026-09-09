"""
Agent Framework -- Vorbereitung für spätere autonome Agenten auf Basis
der Shadow LLM Engine.

Ein `Agent` kann:
    - Aufgaben erhalten
    - planen (über eine austauschbare `plan_fn`, i. d. R. ein LLM-Aufruf)
    - Ergebnisse liefern

Die eigentliche "Intelligenz" (Planung, Tool-Nutzung) wird bewusst nicht
hart verdrahtet, sondern über Callbacks injiziert, die intern die
Shadow LLM API (siehe shadow_engine.api) aufrufen. So bleibt das
Agent-Framework unabhängig von einer konkreten Modellversion.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    PLANNING = "planning"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Task:
    task_id: str
    description: str
    status: TaskStatus = TaskStatus.PENDING
    plan: list[str] = field(default_factory=list)
    result: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    error: Optional[str] = None


# Signatur: (task_description, context) -> Liste von Plan-Schritten
PlanFn = Callable[[str, dict], list[str]]
# Signatur: (step_description, context) -> Ergebnis-String
ExecuteFn = Callable[[str, dict], str]


class Agent:
    """
    Ein einzelner Shadow-Agent.

    `plan_fn` und `execute_fn` sind typischerweise dünne Wrapper um die
    Shadow LLM API (`generate`), die hier absichtlich nicht importiert
    wird, um zirkuläre Abhängigkeiten und eine harte Kopplung an ein
    bestimmtes Modell zu vermeiden.
    """

    def __init__(
        self,
        name: str,
        plan_fn: PlanFn,
        execute_fn: ExecuteFn,
        agent_id: Optional[str] = None,
    ):
        self.name = name
        self.agent_id = agent_id or str(uuid.uuid4())
        self.plan_fn = plan_fn
        self.execute_fn = execute_fn
        self.tasks: dict[str, Task] = {}

    def receive_task(self, description: str) -> Task:
        task = Task(task_id=str(uuid.uuid4()), description=description)
        self.tasks[task.task_id] = task
        return task

    def plan(self, task: Task, context: Optional[dict] = None) -> Task:
        task.status = TaskStatus.PLANNING
        try:
            task.plan = self.plan_fn(task.description, context or {})
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
        return task

    def run(self, task: Task, context: Optional[dict] = None) -> Task:
        context = context or {}
        if not task.plan:
            self.plan(task, context)
            if task.status == TaskStatus.FAILED:
                return task

        task.status = TaskStatus.RUNNING
        step_results = []
        try:
            for step in task.plan:
                step_results.append(self.execute_fn(step, context))
            task.result = "\n".join(step_results)
            task.status = TaskStatus.DONE
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
        return task

    def handle(self, description: str, context: Optional[dict] = None) -> Task:
        """Kompletter Zyklus: Aufgabe erhalten -> planen -> ausführen -> Ergebnis."""
        task = self.receive_task(description)
        return self.run(task, context)
