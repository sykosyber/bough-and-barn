"""Situation pooling. Uniform, derived (enabled-rule set), learned (exact p-vector)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import Enum

from bough.ir import MarkovAutomaton, NodeKind, Situation


class StagingMode(str, Enum):
    UNIFORM = "uniform"
    DERIVED = "derived"
    LEARNED = "learned"


@dataclass(frozen=True, slots=True)
class Stage:
    key: tuple
    signatures: frozenset[str]


@dataclass(frozen=True, slots=True)
class Staging:
    mode: StagingMode
    stages: tuple[Stage, ...]

    @property
    def stage_count(self) -> int:
        return len(self.stages)

    def assignment(self) -> dict[str, int]:
        return {
            signature: index
            for index, stage in enumerate(self.stages)
            for signature in stage.signatures
        }


def _enabled_rules(situation: Situation) -> tuple[str, ...]:
    return tuple(sorted({edge.rule_id for edge in situation.outgoing}))


def _probability_vector(situation: Situation) -> tuple:
    if situation.kind is NodeKind.TERMINAL:
        return ("terminal",)
    if situation.kind is NodeKind.DECISION:
        return ("decision", _enabled_rules(situation))
    masses: dict[str, float] = {}
    for edge in situation.outgoing:
        masses[edge.rule_id] = masses.get(edge.rule_id, 0.0) + (edge.probability or 0.0)
    return ("chance", tuple(sorted((rule_id, round(mass, 12)) for rule_id, mass in masses.items())))


def _key(situation: Situation, mode: StagingMode) -> tuple:
    if mode is StagingMode.UNIFORM:
        return ("situation", situation.signature)
    if mode is StagingMode.DERIVED:
        if situation.kind is NodeKind.TERMINAL:
            return ("terminal",)
        return (situation.kind.value, _enabled_rules(situation))
    if mode is StagingMode.LEARNED:
        return _probability_vector(situation)
    raise ValueError(mode)


def stage(automaton: MarkovAutomaton, mode: StagingMode | str) -> Staging:
    """Pool situations. ``learned`` is an exact descriptor, not a C4 claim."""
    mode = StagingMode(mode)
    buckets: dict[tuple, list[str]] = defaultdict(list)
    for signature, situation in automaton.situations.items():
        buckets[_key(situation, mode)].append(signature)
    stages = tuple(
        Stage(key=key, signatures=frozenset(members))
        for key, members in sorted(buckets.items(), key=lambda item: repr(item[0]))
    )
    return Staging(mode=mode, stages=stages)
