"""Rate refresh versus structural rebuild. Measure; do not claim faster than SSA."""

from __future__ import annotations

import time

from osahr.graph import Hypergraph
from osahr.incremental import RuleDependencySignature
from osahr.pattern import Rule
from osahr.schema import Schema

from bough.errors import BoughRefusal
from bough.expand import _occurrences
from bough.ir import MarkovAutomaton, NodeKind
from bough.spec import BoughModel


def structural_rule_hits(
    rules: tuple[Rule, ...],
    schema: Schema,
    vertex_types: set[str],
    edge_types: set[str],
) -> frozenset[str]:
    """Rule ids whose match relation may change if those types are edited."""
    hits: list[str] = []
    for rule in rules:
        signature = RuleDependencySignature.compile(rule)
        if signature.relevant_to_types(schema, vertex_types, edge_types):
            hits.append(rule.rule_id)
    return frozenset(hits)


def rate_lives_in_graph(graph: Hypergraph) -> bool:
    """Hazards on this fragment are vertex attributes, so they are in the signature."""
    return any(
        name in vertex.attributes
        for vertex in graph.vertices.values()
        for name in ("failure", "repair")
    )


def refresh_probabilities(automaton: MarkovAutomaton, bough_model: BoughModel) -> MarkovAutomaton:
    """Rematch and reweight existing situations. No rewrite, no new nodes.

    If the enabled (rule_id, match_id) set moved, the structure changed and a
    full expand is required. Rate-on-vertex-attribute edits also change G, so
    they are not a same-signature refresh.
    """
    started = time.perf_counter()
    parameters = dict(bough_model.model.parameters)
    for situation in automaton.situations.values():
        if situation.kind is NodeKind.TERMINAL:
            continue
        if situation.kind is NodeKind.DECISION:
            occ = _occurrences(
                situation.graph,
                situation.boundary,
                parameters,
                bough_model.decision_rules,
                evaluate_hazard=False,
            )
            new_keys = {(rule.rule_id, match.match_id) for rule, match, _hazard in occ}
            old_keys = {(edge.rule_id, edge.match_id) for edge in situation.outgoing}
            if new_keys != old_keys:
                raise BoughRefusal(
                    "STRUCTURAL_CHANGE",
                    f"decision matches moved at {situation.signature}; expand again",
                )
            continue
        occ = _occurrences(
            situation.graph,
            situation.boundary,
            parameters,
            bough_model.chance_rules,
            evaluate_hazard=True,
        )
        new_keys = {(rule.rule_id, match.match_id) for rule, match, _hazard in occ}
        old_keys = {(edge.rule_id, edge.match_id) for edge in situation.outgoing}
        if new_keys != old_keys:
            raise BoughRefusal(
                "STRUCTURAL_CHANGE",
                f"chance matches moved at {situation.signature}; expand again",
            )
        total = sum(hazard or 0.0 for _rule, _match, hazard in occ)
        if total <= 0.0:
            raise BoughRefusal("ZERO_ACTIVITY", f"refresh found no activity at {situation.signature}")
        hazards = {(rule.rule_id, match.match_id): hazard for rule, match, hazard in occ}
        for edge in situation.outgoing:
            hazard = hazards[(edge.rule_id, edge.match_id)]
            if hazard is None:
                raise BoughRefusal("INVALID_HAZARD", f"{edge.rule_id} refresh hazard is missing")
            edge.probability = hazard / total
    automaton.refresh_seconds = time.perf_counter() - started
    return automaton
