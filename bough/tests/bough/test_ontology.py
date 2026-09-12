"""Phase-2 ontology fragment: fail/repair coalescence and compression ratio."""

from __future__ import annotations

import math

from osahr.matcher import Matcher
from osahr.rewrite import RewriteEngine

from bough.errors import BoughRefusal
from bough.expand import expand
from bough.families import ROUTE_AB, ontology_model
from bough.infer import reach
from bough.report import report
from bough.signature import situation_signature
from bough.spec import anchored_ids
from bough.staging import stage


def _apply(bough, graph, boundary, match, rule):
    result = RewriteEngine().apply(
        graph=graph,
        boundary=boundary,
        parameters=dict(bough.model.parameters),
        memory={},
        rule=rule,
        match=match,
        time=0.0,
        delta_time=0.0,
        event_index=0,
        event_id="test",
    )
    return result.graph, result.boundary


def _rule(bough, rule_id: str):
    for rule in bough.model.rules:
        if rule.rule_id == rule_id:
            return rule
    raise KeyError(rule_id)


def _matches(bough, graph, rule_id: str):
    rule = _rule(bough, rule_id)
    return Matcher().find_rule_matches(
        graph, rule, parameters=dict(bough.model.parameters), memory={}, time=0.0
    )


def test_available_edges_are_not_anchored() -> None:
    bough = ontology_model()
    assert bough.anchored == frozenset(bough.model.graph.vertices)
    assert bough.model.graph.edges
    assert not (bough.anchored & frozenset(bough.model.graph.edges))


def test_fail_repair_ab_returns_to_start_signature() -> None:
    bough = ontology_model()
    g0, b0 = bough.model.graph, bough.model.boundary
    start = situation_signature(g0, b0, bough.repertoire_hash, bough.anchored)
    fail = _rule(bough, "fail")
    repair = _rule(bough, "repair")
    ab_fail = [
        match
        for match in _matches(bough, g0, "fail")
        if g0.vertices[match.vertex_map["r"]].attributes["uri"] == ROUTE_AB
    ]
    assert len(ab_fail) == 1
    g1, b1 = _apply(bough, g0, b0, ab_fail[0], fail)
    mid = situation_signature(g1, b1, bough.repertoire_hash, bough.anchored)
    assert mid != start
    ab_repair = [
        match
        for match in _matches(bough, g1, "repair")
        if g1.vertices[match.vertex_map["r"]].attributes["uri"] == ROUTE_AB
    ]
    assert len(ab_repair) == 1
    g2, b2 = _apply(bough, g1, b1, ab_repair[0], repair)
    assert situation_signature(g2, b2, bough.repertoire_hash, bough.anchored) == start


def test_anchoring_g0_edges_leaks_recreation_order() -> None:
    bough = ontology_model()
    g0, b0 = bough.model.graph, bough.model.boundary
    leaked = frozenset(g0.vertices) | frozenset(g0.edges)
    fail = _rule(bough, "fail")
    repair = _rule(bough, "repair")
    ab_fail = [
        match
        for match in _matches(bough, g0, "fail")
        if g0.vertices[match.vertex_map["r"]].attributes["uri"] == ROUTE_AB
    ][0]
    g1, b1 = _apply(bough, g0, b0, ab_fail, fail)
    ab_repair = [
        match
        for match in _matches(bough, g1, "repair")
        if g1.vertices[match.vertex_map["r"]].attributes["uri"] == ROUTE_AB
    ][0]
    g2, b2 = _apply(bough, g1, b1, ab_repair, repair)
    start = situation_signature(g0, b0, bough.repertoire_hash, leaked)
    after = situation_signature(g2, b2, bough.repertoire_hash, leaked)
    assert start != after
    assert anchored_ids(g0) == frozenset(g0.vertices)


def test_ontology_copies1_compression_ratio() -> None:
    automaton = expand(ontology_model(1))
    stats = report(automaton)
    assert stats.situation_count == 8
    assert stats.edge_count == 24
    assert stats.uncoalesced_node_count == 25
    assert math.isclose(stats.compression_ratio, 3.125)
    assert stats.truncated is False
    assert stats.compression_ratio > 1.5


def test_ontology_copies2_c1_growth() -> None:
    automaton = expand(ontology_model(2))
    stats = report(automaton)
    assert stats.situation_count == 64
    assert stats.edge_count == 384
    assert stats.uncoalesced_node_count == 385
    assert math.isclose(stats.compression_ratio, 385 / 64)
    assert stats.compression_ratio > 3.125


def test_ontology_reach_refuses_cycle() -> None:
    automaton = expand(ontology_model(1))
    try:
        reach(automaton, "unused")
    except BoughRefusal as exc:
        assert exc.reason == "CYCLIC_AUTOMATON"
    else:
        raise AssertionError("expected CYCLIC_AUTOMATON")


def test_ontology_derived_staging() -> None:
    automaton = expand(ontology_model(1))
    derived = stage(automaton, "derived")
    assert derived.stage_count == 3
    uniform = stage(automaton, "uniform")
    assert uniform.stage_count == 8
