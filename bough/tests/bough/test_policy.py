"""Decision layer: preemption and a hand-solvable protect/ignore MDP."""

from __future__ import annotations

import math

from bough.expand import expand
from bough.families import machine_model, preempt_model
from bough.ir import NodeKind
from bough.policy import machine_terminal_value, optimal_policy


def test_decisions_preempt_chance() -> None:
    automaton = expand(preempt_model())
    root = automaton.situations[automaton.root]
    assert root.kind is NodeKind.DECISION
    assert {edge.rule_id for edge in root.outgoing} == {"choose"}
    assert all(edge.probability is None for edge in root.outgoing)


def test_machine_optimal_policy_is_protect() -> None:
    automaton = expand(machine_model())
    root = automaton.situations[automaton.root]
    assert root.kind is NodeKind.DECISION
    assert {edge.rule_id for edge in root.outgoing} == {"protect", "ignore"}
    policy = optimal_policy(automaton, machine_terminal_value)
    assert math.isclose(policy.value[automaton.root], 1.0)
    assert policy.action[automaton.root] is not None
    assert policy.action[automaton.root][0] == "protect"
    ignore = next(edge for edge in root.outgoing if edge.rule_id == "ignore")
    assert math.isclose(policy.value[ignore.target], 0.5)
    protect = next(edge for edge in root.outgoing if edge.rule_id == "protect")
    assert math.isclose(policy.value[protect.target], 1.0)
    terminals = [s for s in automaton.situations.values() if s.kind is NodeKind.TERMINAL]
    outcomes = {
        next(v.attributes["outcome"] for v in s.graph.vertices.values())
        for s in terminals
    }
    assert outcomes == {"succeeded", "failed"}
