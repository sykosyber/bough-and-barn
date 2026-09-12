"""Exact queries on the compiled jump chain. v0: DAG only."""

from __future__ import annotations

from bough.errors import BoughRefusal
from bough.ir import MarkovAutomaton, NodeKind


def _assert_not_truncated(automaton: MarkovAutomaton) -> None:
    if automaton.truncated:
        raise BoughRefusal(
            "TRUNCATED",
            "query is conditional on a truncated expansion; refuse unlabeled exact mode",
        )


def _assert_dag(automaton: MarkovAutomaton) -> None:
    visiting: set[str] = set()
    seen: set[str] = set()

    def walk(sig: str) -> None:
        if sig in seen:
            return
        if sig in visiting:
            raise BoughRefusal("CYCLIC_AUTOMATON", "v0 reach/path_probability require a DAG")
        visiting.add(sig)
        for edge in automaton.situations[sig].outgoing:
            walk(edge.target)
        visiting.remove(sig)
        seen.add(sig)

    walk(automaton.root)


def path_probability(automaton: MarkovAutomaton, trace: list[tuple[str, str]]) -> float:
    """Exact product along a (rule_id, match_id) trace from the root."""
    _assert_not_truncated(automaton)
    _assert_dag(automaton)
    current = automaton.root
    prob = 1.0
    for rule_id, match_id in trace:
        situation = automaton.situations[current]
        if situation.kind is not NodeKind.CHANCE:
            raise BoughRefusal("NOT_CHANCE", f"trace stepped from {situation.kind} node")
        matches = [
            edge
            for edge in situation.outgoing
            if edge.rule_id == rule_id and edge.match_id == match_id
        ]
        if not matches:
            return 0.0
        if len(matches) != 1 or matches[0].probability is None:
            raise BoughRefusal("AMBIGUOUS_TRACE", f"{rule_id}/{match_id} at {current}")
        prob *= matches[0].probability
        current = matches[0].target
    return prob


def reach(automaton: MarkovAutomaton, label: str) -> tuple[float, int]:
    """Return (probability mass, number of distinct paths) to terminals with ``label``."""
    _assert_not_truncated(automaton)
    _assert_dag(automaton)

    cache: dict[str, tuple[float, int]] = {}

    def mass(sig: str) -> tuple[float, int]:
        if sig in cache:
            return cache[sig]
        situation = automaton.situations[sig]
        if situation.kind is NodeKind.TERMINAL:
            result = (1.0, 1) if situation.label == label else (0.0, 0)
            cache[sig] = result
            return result
        total = 0.0
        paths = 0
        for edge in situation.outgoing:
            child_mass, child_paths = mass(edge.target)
            if edge.probability is None:
                raise BoughRefusal("NOT_CHANCE", "reach on a decision node is phase 4")
            total += edge.probability * child_mass
            paths += child_paths
        cache[sig] = (total, paths)
        return cache[sig]

    return mass(automaton.root)
