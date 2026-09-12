"""Markov automaton IR: situations, florets, edges."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from osahr.boundary import BoundaryState
from osahr.graph import Hypergraph


class NodeKind(str, Enum):
    CHANCE = "chance"
    DECISION = "decision"
    TERMINAL = "terminal"


@dataclass(slots=True)
class Edge:
    source: str
    target: str
    rule_id: str
    match_id: str
    kind: NodeKind
    probability: float | None
    bindings: dict[str, Any]


@dataclass(slots=True)
class Situation:
    signature: str
    kind: NodeKind
    depth: int
    graph: Hypergraph
    boundary: BoundaryState
    label: str | None = None
    outgoing: list[Edge] = field(default_factory=list)


@dataclass(slots=True)
class Horizon:
    max_depth: int | None = None
    max_situations: int = 5000

    def stop(self, depth: int) -> bool:
        return self.max_depth is not None and depth >= self.max_depth


@dataclass(slots=True)
class MarkovAutomaton:
    root: str
    situations: dict[str, Situation]
    uncoalesced_node_count: int
    truncated: bool
    horizon: Horizon
    repertoire_hash: str
    expand_seconds: float = 0.0
    refresh_seconds: float | None = None

    @property
    def situation_count(self) -> int:
        return len(self.situations)

    @property
    def edge_count(self) -> int:
        return sum(len(s.outgoing) for s in self.situations.values())

    @property
    def compression_ratio(self) -> float:
        return self.uncoalesced_node_count / max(self.situation_count, 1)
