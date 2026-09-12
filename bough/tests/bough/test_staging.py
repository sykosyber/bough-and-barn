"""Staging modes and incrementality measurements. No SSA-speed claim."""

from __future__ import annotations

import math

from bough.expand import expand
from bough.families import bits_model, ontology_model
from bough.incrementality import refresh_probabilities, structural_rule_hits
from bough.staging import StagingMode, stage


def test_bits3_derived_staging_pools_enabled_rule_set() -> None:
    automaton = expand(bits_model(3))
    derived = stage(automaton, StagingMode.DERIVED)
    assert derived.stage_count == 2
    uniform = stage(automaton, StagingMode.UNIFORM)
    assert uniform.stage_count == 8
    learned = stage(automaton, StagingMode.LEARNED)
    assert learned.stage_count == 2


def test_refresh_probabilities_idempotent_on_ontology() -> None:
    bough = ontology_model(1)
    automaton = expand(bough)
    before = {
        (edge.source, edge.target, edge.rule_id, edge.match_id, edge.probability)
        for situation in automaton.situations.values()
        for edge in situation.outgoing
    }
    refresh_probabilities(automaton, bough)
    after = {
        (edge.source, edge.target, edge.rule_id, edge.match_id, edge.probability)
        for situation in automaton.situations.values()
        for edge in situation.outgoing
    }
    assert before == after
    assert automaton.refresh_seconds is not None
    assert automaton.refresh_seconds >= 0.0
    assert automaton.expand_seconds > 0.0


def test_structural_hits_available_and_route() -> None:
    bough = ontology_model(1)
    hits = structural_rule_hits(
        bough.model.rules,
        bough.model.graph.schema,
        {"Route"},
        {"Available"},
    )
    assert hits == frozenset({"fail", "repair"})
    token_hits = structural_rule_hits(
        bough.model.rules,
        bough.model.graph.schema,
        {"Token"},
        {"Holds"},
    )
    assert token_hits == frozenset()


def test_refresh_timings_are_recorded_not_an_ssa_claim() -> None:
    bough = bits_model(6)
    automaton = expand(bough)
    refresh_probabilities(automaton, bough)
    assert automaton.expand_seconds >= 0.0
    assert automaton.refresh_seconds is not None
    assert automaton.refresh_seconds >= 0.0
    assert math.isclose(automaton.compression_ratio, 193 / 64)
