"""L0 compile: OSAHR Model + kind overlay, frozen for the jump chain."""

from __future__ import annotations

from dataclasses import dataclass

from osahr.canonical import stable_hash
from osahr.graph import Hypergraph
from osahr.ids import EntityId
from osahr.model import Model
from osahr.pattern import Rule

from bough.errors import BoughRefusal
from bough.kinds import EventKind, EventSpec, validate_event


def repertoire_hash(rules: tuple[Rule, ...]) -> str:
    return stable_hash(tuple(rule.hash for rule in sorted(rules, key=lambda r: r.rule_id)))


def anchored_ids(graph: Hypergraph) -> frozenset[EntityId]:
    """G0 vertices are ontology individuals. Mechanism edges are derived.

    Available (and similar) hyperedges are deleted and recreated with new
    EntityIds. Anchoring G0 edge IDs would make fail→repair a new situation
    forever and pin the compression ratio near 1. Edges that themselves carry
    a ``uri`` are treated as named ontology relations and stay anchored.
    """
    named_edges = frozenset(
        entity_id
        for entity_id, edge in graph.edges.items()
        if "uri" in edge.attributes
    )
    return frozenset(graph.vertices) | named_edges


@dataclass(frozen=True, slots=True)
class BoughModel:
    model: Model
    events: tuple[EventSpec, ...]
    anchored: frozenset[EntityId]
    repertoire_hash: str

    @property
    def chance_rules(self) -> tuple[Rule, ...]:
        return tuple(spec.rule for spec in self.events if spec.kind is EventKind.CHANCE)

    @property
    def decision_rules(self) -> tuple[Rule, ...]:
        return tuple(spec.rule for spec in self.events if spec.kind is EventKind.DECISION)

    def spec_for(self, rule_id: str) -> EventSpec:
        for spec in self.events:
            if spec.rule.rule_id == rule_id:
                return spec
        raise KeyError(rule_id)


def compile_model(model: Model, events: tuple[EventSpec, ...]) -> BoughModel:
    if model.memory:
        raise BoughRefusal("NON_EMPTY_Z", "non-empty memory is anti-coalescent; refuse")
    if model.rule_templates:
        raise BoughRefusal("META_REWRITING", "rule templates are forbidden in v0")
    if model.adaptive_parameters:
        raise BoughRefusal("ADAPTIVE_ASSIGNMENTS", "adaptive parameter registry is frozen-empty in v0")
    event_ids = [spec.event_id for spec in events]
    if len(event_ids) != len(set(event_ids)):
        raise BoughRefusal("DUPLICATE_EVENT", f"duplicate event ids: {event_ids}")
    rule_ids = {rule.rule_id for rule in model.rules}
    for spec in events:
        if spec.rule.rule_id not in rule_ids:
            raise BoughRefusal("UNKNOWN_RULE", f"{spec.event_id} rule is not in the kernel model")
        validate_event(spec)
    return BoughModel(
        model=model,
        events=events,
        anchored=anchored_ids(model.graph),
        repertoire_hash=repertoire_hash(model.rules),
    )
