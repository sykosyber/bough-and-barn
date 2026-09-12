"""Backward induction on a DAG Markov automaton. Preemptive decisions, no discounting."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from bough.errors import BoughRefusal
from bough.infer import _assert_dag, _assert_not_truncated
from bough.ir import MarkovAutomaton, NodeKind, Situation


@dataclass(frozen=True, slots=True)
class Policy:
    value: dict[str, float]
    action: dict[str, tuple[str, str] | None]


def _postorder(automaton: MarkovAutomaton) -> list[str]:
    _assert_not_truncated(automaton)
    _assert_dag(automaton)
    order: list[str] = []
    seen: set[str] = set()
    visiting: set[str] = set()

    def walk(sig: str) -> None:
        if sig in seen:
            return
        if sig in visiting:
            raise BoughRefusal("CYCLIC_AUTOMATON", "optimal_policy requires a DAG")
        visiting.add(sig)
        for edge in automaton.situations[sig].outgoing:
            walk(edge.target)
        visiting.remove(sig)
        seen.add(sig)
        order.append(sig)

    walk(automaton.root)
    return order


def optimal_policy(
    automaton: MarkovAutomaton,
    terminal_value: Callable[[Situation], float],
) -> Policy:
    """Max over decision edges, expectation over chance. Tie-break (rule_id, match_id)."""
    value: dict[str, float] = {}
    action: dict[str, tuple[str, str] | None] = {}
    for signature in _postorder(automaton):
        situation = automaton.situations[signature]
        if situation.kind is NodeKind.TERMINAL or not situation.outgoing:
            value[signature] = float(terminal_value(situation))
            action[signature] = None
            continue
        if situation.kind is NodeKind.CHANCE:
            total = 0.0
            for edge in situation.outgoing:
                if edge.probability is None:
                    raise BoughRefusal("NOT_CHANCE", f"chance edge {edge.rule_id} has no probability")
                total += edge.probability * value[edge.target]
            value[signature] = total
            action[signature] = None
            continue
        if situation.kind is not NodeKind.DECISION:
            raise BoughRefusal("UNKNOWN_KIND", situation.kind.value)
        best: tuple[float, str, str] | None = None
        for edge in situation.outgoing:
            candidate = (value[edge.target], edge.rule_id, edge.match_id)
            if best is None or candidate[0] > best[0] or (
                candidate[0] == best[0] and (candidate[1], candidate[2]) < (best[1], best[2])
            ):
                best = candidate
        if best is None:
            raise BoughRefusal("EMPTY_DECISION", f"decision node {signature} has no actions")
        value[signature] = best[0]
        action[signature] = (best[1], best[2])
    return Policy(value=value, action=action)


def machine_terminal_value(situation: Situation) -> float:
    for vertex in situation.graph.vertices.values():
        if vertex.type_id != "Machine":
            continue
        if vertex.attributes["outcome"] == "succeeded":
            return 1.0
        if vertex.attributes["outcome"] == "failed":
            return 0.0
        return 0.0
    return 0.0
