"""Inference vs hand values and a kernel ensemble on the bits family."""

from __future__ import annotations

import math

from osahr.analysis import run_ensemble

from bough.expand import expand
from bough.families import bits_model
from bough.infer import path_probability, reach


def _all_on_label(n: int):
    def label(situation) -> str | None:
        ons = sum(1 for vertex in situation.graph.vertices.values() if vertex.attributes["on"])
        if ons == n:
            return "all-on"
        return None

    return label


def test_bits2_path_probability_and_reach() -> None:
    automaton = expand(bits_model(2), label=_all_on_label(2))
    mass, paths = reach(automaton, "all-on")
    assert math.isclose(mass, 1.0)
    assert paths == 2
    root = automaton.situations[automaton.root]
    traces = []
    for first in root.outgoing:
        mid = automaton.situations[first.target]
        for second in mid.outgoing:
            traces.append([(first.rule_id, first.match_id), (second.rule_id, second.match_id)])
    probs = [path_probability(automaton, trace) for trace in traces]
    assert len(probs) == 2
    assert all(math.isclose(p, 0.5) for p in probs)
    assert math.isclose(sum(probs), 1.0)


def test_bits2_reach_matches_ensemble_absorption() -> None:
    bough = bits_model(2)
    automaton = expand(bough, label=_all_on_label(2))
    mass, _paths = reach(automaton, "all-on")
    result = run_ensemble(
        bough.model,
        replicates=20,
        root_seed=7,
        target_time=40.0,
        first_passage=lambda runtime: all(
            vertex.attributes["on"] for vertex in runtime.graph.vertices.values()
        ),
    )
    absorbed = sum(1 for sample in result.samples if sample.first_passage_time is not None)
    empirical = absorbed / len(result.samples)
    assert math.isclose(mass, 1.0)
    assert empirical == 1.0
