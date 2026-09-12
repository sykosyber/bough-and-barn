"""Every compilation result carries ratio, horizon, and refusals."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from bough.ir import MarkovAutomaton


@dataclass(frozen=True, slots=True)
class CompilationReport:
    situation_count: int
    uncoalesced_node_count: int
    edge_count: int
    compression_ratio: float
    truncated: bool
    max_depth: int | None
    max_situations: int
    root: str
    expand_seconds: float | None = None
    refresh_seconds: float | None = None
    stage_count: int | None = None
    staging_mode: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def report(automaton: MarkovAutomaton, *, stage_count: int | None = None, staging_mode: str | None = None) -> CompilationReport:
    return CompilationReport(
        situation_count=automaton.situation_count,
        uncoalesced_node_count=automaton.uncoalesced_node_count,
        edge_count=automaton.edge_count,
        compression_ratio=automaton.compression_ratio,
        truncated=automaton.truncated,
        max_depth=automaton.horizon.max_depth,
        max_situations=automaton.horizon.max_situations,
        root=automaton.root,
        expand_seconds=automaton.expand_seconds,
        refresh_seconds=automaton.refresh_seconds,
        stage_count=stage_count,
        staging_mode=staging_mode,
    )
