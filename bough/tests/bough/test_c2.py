"""C2: exact reach vs all three OSAHR schedulers on DAG families."""

from __future__ import annotations

import math

from bough.compare import KERNEL_SCHEDULERS, agree_first_passage, bits_all_on, hoeffding_radius, race_winner_a
from bough.expand import expand
from bough.families import bits_all_on_label, bits_model, race_model, race_terminal_label
from bough.infer import path_probability, reach


def test_race_exact_reach_is_two_thirds() -> None:
    automaton = expand(race_model(2.0, 1.0), label=race_terminal_label)
    mass_a, paths_a = reach(automaton, "a")
    mass_b, paths_b = reach(automaton, "b")
    assert math.isclose(mass_a, 2.0 / 3.0)
    assert math.isclose(mass_b, 1.0 / 3.0)
    assert paths_a == 1
    assert paths_b == 1
    root = automaton.situations[automaton.root]
    take_a = next(edge for edge in root.outgoing if edge.rule_id == "take-a")
    assert math.isclose(path_probability(automaton, [(take_a.rule_id, take_a.match_id)]), 2.0 / 3.0)


def test_hoeffding_radius_rejects_certainty_against_two_thirds() -> None:
    n = 96
    radius = hoeffding_radius(n)
    assert radius < 1.0 / 3.0
    assert abs(1.0 - 2.0 / 3.0) > radius


def test_bits2_absorption_on_every_kernel_scheduler() -> None:
    bough = bits_model(2)
    automaton = expand(bough, label=bits_all_on_label(2))
    mass, paths = reach(automaton, "all-on")
    assert math.isclose(mass, 1.0)
    assert paths == 2
    rows = agree_first_passage(
        bough.model,
        bits_all_on,
        mass,
        event_count=2,
        replicates=12,
        root_seed=11,
    )
    assert {row.scheduler for row in rows} == {kind.value for kind in KERNEL_SCHEDULERS}
    assert all(row.empirical == 1.0 for row in rows)
    assert all(row.within_radius for row in rows)


def test_race_reach_agrees_with_every_kernel_scheduler() -> None:
    bough = race_model(2.0, 1.0)
    automaton = expand(bough, label=race_terminal_label)
    mass, _paths = reach(automaton, "a")
    rows = agree_first_passage(
        bough.model,
        race_winner_a,
        mass,
        event_count=1,
        replicates=96,
        root_seed=23,
    )
    assert tuple(row.scheduler for row in rows) == tuple(kind.value for kind in KERNEL_SCHEDULERS)
    assert all(row.within_radius for row in rows)
    assert all(0.0 < row.empirical < 1.0 for row in rows)
