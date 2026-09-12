"""Compile a family and print headline numbers. No UI."""

from __future__ import annotations

import argparse
import json

from bough.compare import agree_first_passage, bits_all_on, race_winner_a
from bough.cypher import automaton_to_cypher, try_push_cypher
from bough.expand import expand
from bough.families import (
    bits_all_on_label,
    bits_model,
    machine_model,
    ontology_model,
    race_model,
    race_terminal_label,
)
from bough.incrementality import refresh_probabilities
from bough.infer import reach
from bough.ir import Horizon
from bough.policy import machine_terminal_value, optimal_policy
from bough.report import report
from bough.staging import stage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bough")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_bits = sub.add_parser("bits", help="expand the irreversible-bits family")
    p_bits.add_argument("-n", type=int, default=4)
    p_bits.add_argument("--max-situations", type=int, default=5000)
    p_bits.add_argument("--max-depth", type=int, default=None)

    p_ont = sub.add_parser("ontology", help="phase-2 ontology fragment compression")
    p_ont.add_argument("--copies", type=int, default=1)
    p_ont.add_argument("--max-situations", type=int, default=5000)

    p_mac = sub.add_parser("machine", help="hand-solvable protect/ignore MDP")

    p_cy = sub.add_parser("cypher", help="print Neo4j inspection Cypher for a family")
    p_cy.add_argument("family", choices=("bits", "ontology", "machine"))
    p_cy.add_argument("-n", type=int, default=2)
    p_cy.add_argument("--copies", type=int, default=1)
    p_cy.add_argument("--push", action="store_true", help="push if NEO4J_URI is set")

    p_c2 = sub.add_parser("c2", help="reach() vs OSAHR direct_ssa / next_reaction / thinning")
    p_c2.add_argument("--replicates", type=int, default=96)
    p_c2.add_argument("--root-seed", type=int, default=23)

    args = parser.parse_args(argv)

    if args.cmd == "bits":
        bough = bits_model(args.n)
        automaton = expand(
            bough,
            horizon=Horizon(max_depth=args.max_depth, max_situations=args.max_situations),
            label=bits_all_on_label(args.n),
        )
        refresh_probabilities(automaton, bough)
        derived = stage(automaton, "derived")
        stats = report(automaton, stage_count=derived.stage_count, staging_mode="derived").to_dict()
        if not automaton.truncated:
            mass, paths = reach(automaton, "all-on")
            stats["reach_all_on"] = mass
            stats["paths_all_on"] = paths
        print(json.dumps(stats, indent=2, sort_keys=True))
        return 0

    if args.cmd == "ontology":
        bough = ontology_model(args.copies)
        automaton = expand(bough, horizon=Horizon(max_situations=args.max_situations))
        refresh_probabilities(automaton, bough)
        derived = stage(automaton, "derived")
        stats = report(automaton, stage_count=derived.stage_count, staging_mode="derived").to_dict()
        routes = 3 * args.copies
        stats["routes"] = routes
        stats["expected_situations"] = 2**routes
        stats["cyclic"] = True
        stats["speed_claim"] = (
            "expand_seconds vs refresh_seconds on this automaton only; not a claim versus SSA"
        )
        print(json.dumps(stats, indent=2, sort_keys=True))
        return 0

    if args.cmd == "machine":
        bough = machine_model()
        automaton = expand(bough)
        policy = optimal_policy(automaton, machine_terminal_value)
        stats = report(automaton).to_dict()
        stats["root_value"] = policy.value[automaton.root]
        stats["root_action"] = list(policy.action[automaton.root] or ())
        print(json.dumps(stats, indent=2, sort_keys=True))
        return 0

    if args.cmd == "cypher":
        if args.family == "bits":
            automaton = expand(bits_model(args.n), label=bits_all_on_label(args.n))
        elif args.family == "ontology":
            automaton = expand(ontology_model(args.copies))
        else:
            automaton = expand(machine_model())
        text = automaton_to_cypher(automaton)
        print(text, end="")
        if args.push:
            print(json.dumps(try_push_cypher(text), indent=2, sort_keys=True))
        return 0

    if args.cmd == "c2":
        race = race_model(2.0, 1.0)
        race_auto = expand(race, label=race_terminal_label)
        mass_a, paths_a = reach(race_auto, "a")
        race_rows = agree_first_passage(
            race.model,
            race_winner_a,
            mass_a,
            event_count=1,
            replicates=args.replicates,
            root_seed=args.root_seed,
        )
        bits = bits_model(2)
        bits_auto = expand(bits, label=bits_all_on_label(2))
        mass_on, paths_on = reach(bits_auto, "all-on")
        bits_rows = agree_first_passage(
            bits.model,
            bits_all_on,
            mass_on,
            event_count=2,
            replicates=min(args.replicates, 24),
            root_seed=args.root_seed,
        )
        payload = {
            "claim": "C2",
            "note": "jump-chain probability vs kernel schedulers; not a speed claim",
            "race": {
                "exact_reach_a": mass_a,
                "paths_a": paths_a,
                "schedulers": [row.to_dict() for row in race_rows],
            },
            "bits2": {
                "exact_reach_all_on": mass_on,
                "paths_all_on": paths_on,
                "schedulers": [row.to_dict() for row in bits_rows],
            },
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
