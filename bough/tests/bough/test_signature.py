"""Tier-1 signature tests. Independent pairs are hand-built, not causal.py."""

from __future__ import annotations

from osahr.matcher import Matcher
from osahr.rewrite import RewriteEngine

from bough.errors import BoughRefusal
from bough.families import bits_model, token_attach_model
from bough.signature import situation_signature


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


def _matches(bough, graph):
    rule = bough.chance_rules[0]
    return Matcher().find_rule_matches(
        graph, rule, parameters=dict(bough.model.parameters), memory={}, time=0.0
    )


def test_independent_flips_confluent() -> None:
    bough = bits_model(2)
    rule = bough.chance_rules[0]
    g0, b0 = bough.model.graph, bough.model.boundary
    matches = _matches(bough, g0)
    assert len(matches) == 2
    m0, m1 = matches

    g_ab, b_ab = _apply(bough, g0, b0, m0, rule)
    m1_after = [
        m
        for m in _matches(bough, g_ab)
        if m.vertex_map["s"] == m1.vertex_map["s"]
    ][0]
    g_ab, b_ab = _apply(bough, g_ab, b_ab, m1_after, rule)

    g_ba, b_ba = _apply(bough, g0, b0, m1, rule)
    m0_after = [
        m
        for m in _matches(bough, g_ba)
        if m.vertex_map["s"] == m0.vertex_map["s"]
    ][0]
    g_ba, b_ba = _apply(bough, g_ba, b_ba, m0_after, rule)

    sig_ab = situation_signature(g_ab, b_ab, bough.repertoire_hash, bough.anchored)
    sig_ba = situation_signature(g_ba, b_ba, bough.repertoire_hash, bough.anchored)
    assert sig_ab == sig_ba


def test_dependent_sites_discriminate() -> None:
    bough = bits_model(2)
    rule = bough.chance_rules[0]
    g0, b0 = bough.model.graph, bough.model.boundary
    m0, m1 = _matches(bough, g0)
    g_a, b_a = _apply(bough, g0, b0, m0, rule)
    g_b, b_b = _apply(bough, g0, b0, m1, rule)
    sig_a = situation_signature(g_a, b_a, bough.repertoire_hash, bough.anchored)
    sig_b = situation_signature(g_b, b_b, bough.repertoire_hash, bough.anchored)
    sig_0 = situation_signature(g0, b0, bough.repertoire_hash, bough.anchored)
    assert sig_a != sig_b
    assert sig_a != sig_0
    assert sig_b != sig_0


def test_derived_token_attach_confluent() -> None:
    bough = token_attach_model()
    rule = bough.chance_rules[0]
    g0, b0 = bough.model.graph, bough.model.boundary
    m0, m1 = _matches(bough, g0)

    g_ab, b_ab = _apply(bough, g0, b0, m0, rule)
    m1_after = [m for m in _matches(bough, g_ab) if m.vertex_map["p"] == m1.vertex_map["p"]][0]
    g_ab, b_ab = _apply(bough, g_ab, b_ab, m1_after, rule)

    g_ba, b_ba = _apply(bough, g0, b0, m1, rule)
    m0_after = [m for m in _matches(bough, g_ba) if m.vertex_map["p"] == m0.vertex_map["p"]][0]
    g_ba, b_ba = _apply(bough, g_ba, b_ba, m0_after, rule)

    assert situation_signature(g_ab, b_ab, bough.repertoire_hash, bough.anchored) == situation_signature(
        g_ba, b_ba, bough.repertoire_hash, bough.anchored
    )


def test_identical_derived_tokens_refuse_residual_symmetry() -> None:
    bough = token_attach_model()
    rule = bough.chance_rules[0]
    g0, b0 = bough.model.graph, bough.model.boundary
    person = _matches(bough, g0)[0]
    g1, b1 = _apply(bough, g0, b0, person, rule)
    again = [m for m in _matches(bough, g1) if m.vertex_map["p"] == person.vertex_map["p"]][0]
    g2, b2 = _apply(bough, g1, b1, again, rule)
    try:
        situation_signature(g2, b2, bough.repertoire_hash, bough.anchored)
    except BoughRefusal as exc:
        assert exc.reason == "RESIDUAL_SYMMETRY"
    else:
        raise AssertionError("expected RESIDUAL_SYMMETRY")
