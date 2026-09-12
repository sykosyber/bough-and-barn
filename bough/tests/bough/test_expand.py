"""Expansion: BFS, coalescence counts, permutation invariance."""

from __future__ import annotations

import math

from bough.expand import expand
from bough.families import bits_model
from bough.ir import Horizon, NodeKind
from bough.report import report


def test_bits2_hand_counts() -> None:
    automaton = expand(bits_model(2))
    stats = report(automaton)
    assert stats.situation_count == 4
    assert stats.uncoalesced_node_count == 5
    assert stats.edge_count == 4
    assert math.isclose(stats.compression_ratio, 5 / 4)
    assert stats.truncated is False
    terminals = [s for s in automaton.situations.values() if s.kind is NodeKind.TERMINAL]
    assert len(terminals) == 1


def test_bits3_hand_counts() -> None:
    automaton = expand(bits_model(3))
    stats = report(automaton)
    assert stats.situation_count == 8
    assert stats.uncoalesced_node_count == 13
    assert stats.edge_count == 12


def test_two_expands_are_deterministic() -> None:
    first = expand(bits_model(3))
    second = expand(bits_model(3))
    assert set(first.situations) == set(second.situations)
    left = {
        (edge.source, edge.target, edge.rule_id, edge.match_id, edge.probability)
        for situation in first.situations.values()
        for edge in situation.outgoing
    }
    right = {
        (edge.source, edge.target, edge.rule_id, edge.match_id, edge.probability)
        for situation in second.situations.values()
        for edge in situation.outgoing
    }
    assert left == right


def test_horizon_truncation_is_labeled() -> None:
    automaton = expand(bits_model(4), horizon=Horizon(max_depth=1))
    assert all(
        s.kind is NodeKind.TERMINAL or s.signature == automaton.root
        for s in automaton.situations.values()
    )
    assert automaton.horizon.max_depth == 1
