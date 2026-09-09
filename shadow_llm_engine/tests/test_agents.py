"""Tests für das Agenten-Framework (System 4): Zielerfüllung, Schwarm-
kommunikation, Speicher, Werkzeuge, Ergebnisbewertung."""

from __future__ import annotations

import pytest

from shadow_engine.agents import (
    Agent,
    AgentMemory,
    CalculatorTool,
    GoalAgent,
    GoalRun,
    MessageBus,
    ResultEvaluator,
    SwarmAgent,
    SwarmResult,
    Task,
    TaskStatus,
    Tool,
    ToolRegistry,
    default_tools,
)


def _make_plan_fn(steps=("schritt 1", "schritt 2")):
    return lambda desc, ctx: list(steps)


def _make_exec_fn(prefix="ergebnis"):
    return lambda step, ctx: f"{prefix} für {step}"


# ---------------------------------------------------------------------- #
# Speicher
# ---------------------------------------------------------------------- #


def test_agent_memory_store_recall():
    mem = AgentMemory()
    mem.remember("name", "shadow")
    assert mem.recall("name") == "shadow"
    assert mem.recall("missing", default="x") == "x"
    mem.push_working("w1")
    assert mem.pop_working() == "w1"


# ---------------------------------------------------------------------- #
# Werkzeuge
# ---------------------------------------------------------------------- #


def test_tool_registry_register_and_call():
    reg = ToolRegistry()
    reg.register(Tool(name="echo", description="d", run_fn=lambda x: x.upper()))
    assert reg.call("echo", "hi") == "HI"
    with pytest.raises(KeyError):
        reg.call("missing", "x")


def test_calculator_tool():
    assert CalculatorTool.run("2 + 3 * 4") == 14.0
    with pytest.raises(ValueError):
        CalculatorTool.run("import os")  # verbotene Zeichen


def test_default_tools_present():
    tools = default_tools()
    names = {t["name"] for t in tools.list()}
    assert {"calculator", "regex"} <= names


def test_agent_use_tool_records_in_memory():
    a = Agent(name="a", plan_fn=_make_plan_fn(), execute_fn=_make_exec_fn())
    result = a.use_tool("calculator", "6*7")
    assert result == 42.0
    assert any(m.get("tool") == "calculator" for m in a.memory.working_memory)


# ---------------------------------------------------------------------- #
# Ergebnisbewertung
# ---------------------------------------------------------------------- #


def test_result_evaluator_length_and_keywords():
    ev = ResultEvaluator(min_length=5, contains=["shadow"])
    assert ev.evaluate("das ist shadow ergebnis", "t", {}).passed is True
    res = ev.evaluate("kurz", "t", {})
    assert res.passed is False


def test_result_evaluator_predicate():
    ev = ResultEvaluator(predicate=lambda r, t, c: (len(r) > 3, "zu kurz via pred"))
    assert ev.evaluate("ok", "t", {}).passed is False


def test_agent_run_marks_failed_when_evaluation_fails():
    ev = ResultEvaluator(min_length=100)  # nie bestanden
    a = Agent(name="a", plan_fn=_make_plan_fn(), execute_fn=_make_exec_fn(), evaluator=ev)
    task = a.handle("aufgabe")
    assert task.status == TaskStatus.FAILED


# ---------------------------------------------------------------------- #
# Ziel-Agent (Zielerfüllung)
# ---------------------------------------------------------------------- #


def test_goal_agent_achieves_after_iterations():
    calls = {"n": 0}

    def evaluator(goal, results):
        calls["n"] += 1
        if len(results) >= 2:
            return True, None
        return False, "nächster schritt"

    ga = GoalAgent(name="goal", plan_fn=_make_plan_fn(), execute_fn=_make_exec_fn(),
                   goal_evaluator_fn=evaluator, max_iterations=5)
    run = ga.pursue_goal("erreiche X")
    assert run.achieved is True
    assert len(run.subtasks) == 2


def test_goal_agent_stops_at_max_iterations():
    def evaluator(goal, results):
        return False, "weiter"
    ga = GoalAgent(name="goal", plan_fn=_make_plan_fn(), execute_fn=_make_exec_fn(),
                   goal_evaluator_fn=evaluator, max_iterations=3)
    run = ga.pursue_goal("unendlich")
    assert run.achieved is False
    assert run.iterations == 3


# ---------------------------------------------------------------------- #
# Schwarm
# ---------------------------------------------------------------------- #


def test_message_bus_pubsub():
    bus = MessageBus()
    bus.subscribe("agent-a")
    assert bus.publish("agent-a", {"x": 1}) is True
    assert bus.publish("agent-b", {"x": 2}) is False  # nicht subscribed
    msgs = bus.drain("agent-a")
    assert msgs == [{"x": 1}]


def test_swarm_agent_roles_spawned():
    plan_fns = {r: _make_plan_fn((r,)) for r in ["research", "coding", "testing", "review"]}
    exec_fns = {r: _make_exec_fn(r) for r in plan_fns}
    swarm = SwarmAgent(plan_fns=plan_fns, execute_fns=exec_fns)
    assert set(swarm.sub_agents.keys()) == {"research", "coding", "testing", "review"}


def test_swarm_dispatch_returns_merged_result():
    plan_fns = {"research": lambda d, c: ["r:" + d], "coding": lambda d, c: ["c:" + d]}
    exec_fns = {"research": lambda s, c: "R-" + s, "coding": lambda s, c: "C-" + s}
    swarm = SwarmAgent(plan_fns=plan_fns, execute_fns=exec_fns, roles=["research", "coding"])
    result = swarm.dispatch(["aufgabe 1", "aufgabe 2"])
    assert isinstance(result, SwarmResult)
    assert "R-" in result.merged_result
    assert "C-" in result.merged_result


def test_swarm_pursue_goal_iterates():
    plan_fns = {"research": _make_plan_fn(), "coding": _make_plan_fn()}
    exec_fns = {"research": _make_exec_fn(), "coding": _make_exec_fn()}
    swarm = SwarmAgent(plan_fns=plan_fns, execute_fns=exec_fns, roles=["research", "coding"])

    def evaluator(goal, results):
        if len(results) >= 2:
            return True, None
        return False, "mehr"

    result = swarm.pursue_goal("schwarm ziel", goal_evaluator=evaluator)
    assert len(result.subtasks) >= 2
