"""
Ziel-Agent (GoalAgent): verfolgt ein übergeordnetes Ziel und erstellt
selbstständig Unteraufgaben, bis das Ziel erreicht ist oder ein
Iterationslimit erreicht wird.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

from shadow_engine.agents.agent import Agent, Task, TaskStatus, PlanFn, ExecuteFn

# Signatur: (goal, bisherige Ergebnisse) -> (ist_ziel_erreicht, naechste_unteraufgabe_oder_None)
GoalEvaluatorFn = Callable[[str, list[str]], tuple[bool, Optional[str]]]


@dataclass
class GoalRun:
    goal_id: str
    goal: str
    subtasks: list[Task] = field(default_factory=list)
    achieved: bool = False
    iterations: int = 0


class GoalAgent(Agent):
    """
    Erweiterung von `Agent` um Ziel-Verfolgung: statt einer festen Aufgabe
    wird ein Ziel übergeben. `goal_evaluator_fn` entscheidet nach jeder
    Unteraufgabe, ob das Ziel erreicht ist oder welche Unteraufgabe als
    nächstes erstellt werden soll.
    """

    def __init__(
        self,
        name: str,
        plan_fn: PlanFn,
        execute_fn: ExecuteFn,
        goal_evaluator_fn: GoalEvaluatorFn,
        max_iterations: int = 10,
        agent_id: Optional[str] = None,
    ):
        super().__init__(name, plan_fn, execute_fn, agent_id)
        self.goal_evaluator_fn = goal_evaluator_fn
        self.max_iterations = max_iterations

    def pursue_goal(self, goal: str, context: Optional[dict] = None) -> GoalRun:
        context = context or {}
        run = GoalRun(goal_id=str(uuid.uuid4()), goal=goal)
        results_so_far: list[str] = []

        current_subtask_desc: Optional[str] = goal
        while current_subtask_desc and run.iterations < self.max_iterations:
            run.iterations += 1
            task = self.handle(current_subtask_desc, context)
            run.subtasks.append(task)

            if task.status == TaskStatus.DONE and task.result:
                results_so_far.append(task.result)
            elif task.status == TaskStatus.FAILED:
                break

            achieved, next_subtask = self.goal_evaluator_fn(goal, results_so_far)
            run.achieved = achieved
            if achieved:
                break
            current_subtask_desc = next_subtask

        return run
