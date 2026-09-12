"""BFS expansion over the embedded jump chain."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

from osahr.boundary import BoundaryState
from osahr.canonical import canonical_equal
from osahr.graph import Hypergraph
from osahr.matcher import Matcher, build_expression_context
from osahr.pattern import Rule
from osahr.rewrite import RewriteEngine

from bough.errors import BoughRefusal
from bough.ir import Edge, Horizon, MarkovAutomaton, NodeKind, Situation
from bough.kinds import EventKind
from bough.signature import situation_signature
from bough.spec import BoughModel

LabelFn = Callable[[Situation], str | None]


def _occurrences(
    graph: Hypergraph,
    boundary: BoundaryState,
    parameters: dict,
    rules: tuple[Rule, ...],
    *,
    evaluate_hazard: bool,
) -> list[tuple[Rule, object, float | None]]:
    matcher = Matcher()
    engine = RewriteEngine()
    found: list[tuple[Rule, object, float | None]] = []
    for rule in rules:
        matches = matcher.find_rule_matches(
            graph, rule, parameters=parameters, memory={}, time=0.0
        )
        for match in matches:
            if not engine.is_applicable(
                graph=graph, boundary=boundary, rule=rule, match=match
            ):
                continue
            hazard = None
            if evaluate_hazard:
                context = build_expression_context(
                    graph, match, parameters=parameters, memory={}, time=0.0
                )
                hazard = float(rule.hazard.evaluate(context))
                if hazard < 0.0 or hazard != hazard:  # NaN
                    raise BoughRefusal("INVALID_HAZARD", f"{rule.rule_id} hazard {hazard!r}")
            found.append((rule, match, hazard))
    found.sort(key=lambda item: (item[0].rule_id, item[1].match_id))
    return found


def _apply(
    graph: Hypergraph,
    boundary: BoundaryState,
    parameters: dict,
    rule: Rule,
    match: object,
) -> tuple[Hypergraph, BoundaryState]:
    result = RewriteEngine().apply(
        graph=graph,
        boundary=boundary,
        parameters=parameters,
        memory={},
        rule=rule,
        match=match,
        time=0.0,
        delta_time=0.0,
        event_index=0,
        event_id=f"bough:{rule.rule_id}:{match.match_id}",
    )
    if result.memory_after:
        raise BoughRefusal("NON_EMPTY_Z", "rewrite produced history memory")
    if not canonical_equal(result.parameter_after, parameters):
        raise BoughRefusal("ADAPTIVE_ASSIGNMENTS", "rewrite mutated Theta")
    return result.graph, result.boundary


def expand(
    bough_model: BoughModel,
    *,
    horizon: Horizon | None = None,
    label: LabelFn | None = None,
    matcher_backend: str = "reference",
) -> MarkovAutomaton:
    if matcher_backend not in {"reference", "indexed"}:
        raise BoughRefusal("UNKNOWN_MATCHER", matcher_backend)
    started = time.perf_counter()
    horizon = horizon or Horizon()
    graph0 = bough_model.model.graph
    boundary0 = bough_model.model.boundary
    parameters = dict(bough_model.model.parameters)
    anchored = bough_model.anchored
    rhash = bough_model.repertoire_hash

    root_sig = situation_signature(graph0, boundary0, rhash, anchored)
    root = Situation(root_sig, NodeKind.CHANCE, 0, graph0.clone(), boundary0.clone())
    seen = {root_sig: root}
    frontier: deque[Situation] = deque([root])
    uncoalesced = 1
    truncated = False

    while frontier:
        if len(seen) >= horizon.max_situations and any(
            True for s in frontier if s.signature in seen
        ):
            # Stop adding new situations; remaining frontier is truncated.
            pass
        situation = frontier.popleft()
        if horizon.stop(situation.depth):
            situation.kind = NodeKind.TERMINAL
            situation.label = label(situation) if label else "horizon"
            continue

        if bough_model.decision_rules:
            dec = _occurrences(
                situation.graph,
                situation.boundary,
                parameters,
                bough_model.decision_rules,
                evaluate_hazard=False,
            )
        else:
            dec = []
        cha = _occurrences(
            situation.graph,
            situation.boundary,
            parameters,
            bough_model.chance_rules,
            evaluate_hazard=True,
        )
        occ = dec if dec else cha
        if not occ:
            situation.kind = NodeKind.TERMINAL
            situation.label = label(situation) if label else "dead"
            continue

        situation.kind = NodeKind.DECISION if dec else NodeKind.CHANCE
        total = sum(h or 0.0 for _, _, h in occ) if situation.kind is NodeKind.CHANCE else None
        if situation.kind is NodeKind.CHANCE and (total is None or total <= 0.0):
            raise BoughRefusal("ZERO_ACTIVITY", f"chance node {situation.signature} has no positive activity")

        for rule, match, hazard in occ:
            if len(seen) >= horizon.max_situations:
                truncated = True
                situation.kind = NodeKind.TERMINAL
                situation.label = situation.label or "truncated"
                situation.outgoing.clear()
                break
            post_g, post_b = _apply(
                situation.graph, situation.boundary, parameters, rule, match
            )
            sig = situation_signature(post_g, post_b, rhash, anchored)
            target = seen.get(sig)
            uncoalesced += 1
            if target is None:
                target = Situation(
                    sig, NodeKind.CHANCE, situation.depth + 1, post_g, post_b
                )
                seen[sig] = target
                frontier.append(target)
            probability = (hazard / total) if situation.kind is NodeKind.CHANCE else None
            situation.outgoing.append(
                Edge(
                    source=situation.signature,
                    target=sig,
                    rule_id=rule.rule_id,
                    match_id=match.match_id,
                    kind=situation.kind,
                    probability=probability,
                    bindings=dict(match.bindings),
                )
            )

        if label and situation.kind is NodeKind.TERMINAL:
            situation.label = label(situation)

    if label:
        for situation in seen.values():
            tagged = label(situation)
            if tagged is not None:
                situation.label = tagged

    return MarkovAutomaton(
        root=root_sig,
        situations=seen,
        uncoalesced_node_count=uncoalesced,
        truncated=truncated,
        horizon=horizon,
        repertoire_hash=rhash,
        expand_seconds=time.perf_counter() - started,
    )
