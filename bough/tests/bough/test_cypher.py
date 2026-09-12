"""Cypher inspection export. The expander never talks to Neo4j."""

from __future__ import annotations

from bough.cypher import automaton_to_cypher, try_push_cypher
from bough.expand import expand
from bough.families import bits_model, machine_model


def test_bits2_cypher_contains_nodes_and_jumps() -> None:
    automaton = expand(bits_model(2))
    text = automaton_to_cypher(automaton)
    assert "inspection only" in text
    assert text.count("MERGE (s:Situation") == 4
    assert text.count("CREATE (a)-[:JUMP") == 4
    assert "kind: 'chance'" in text
    assert "probability:" in text
    assert automaton.root in text


def test_machine_cypher_exports_null_decision_probability() -> None:
    text = automaton_to_cypher(expand(machine_model()))
    assert "kind: 'decision'" in text
    assert "probability: null" in text
    assert "rule_id: 'protect'" in text


def test_push_without_uri_is_noop() -> None:
    result = try_push_cypher("RETURN 1;", uri=None)
    assert result["pushed"] is False
    assert "NEO4J_URI" in result["reason"]
