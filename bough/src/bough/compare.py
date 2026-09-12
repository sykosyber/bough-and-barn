"""C2: Bough reach() vs OSAHR's three exact schedulers on a DAG.

This is a jump-chain probability comparison, not a speed claim. Thinning is
included as a scheduler identity, not because hazards vary with time (Bough
refuses those). The Hoeffding radius is a regression alarm, not a proof of
distributional equality.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass

from osahr.analysis import run_ensemble
from osahr.model import Model, RuntimeConfig
from osahr.runtime import Runtime
from osahr.schedulers import SchedulerKind

KERNEL_SCHEDULERS: tuple[SchedulerKind, ...] = (
    SchedulerKind.DIRECT_SSA,
    SchedulerKind.NEXT_REACTION,
    SchedulerKind.THINNING,
)


def hoeffding_radius(n: int, alpha: float = 1e-6) -> float:
    """Additive radius such that P(|p̂ − p| > ε) ≤ α under independent Bernoulli draws."""
    if n <= 0:
        raise ValueError("n must be positive")
    if not 0.0 < alpha < 1.0:
        raise ValueError("alpha must be in (0, 1)")
    return math.sqrt(math.log(2.0 / alpha) / (2.0 * n))


def first_passage_frequency(
    model: Model,
    predicate: Callable[[Runtime], bool],
    *,
    scheduler: SchedulerKind,
    replicates: int,
    root_seed: int,
    event_count: int,
    matcher_backend: str = "reference",
) -> float:
    result = run_ensemble(
        model,
        replicates=replicates,
        root_seed=root_seed,
        event_count=event_count,
        config=RuntimeConfig(scheduler=scheduler, matcher_backend=matcher_backend),
        first_passage=predicate,
    )
    hits = sum(1 for sample in result.samples if sample.first_passage_time is not None)
    return hits / replicates


@dataclass(frozen=True, slots=True)
class SchedulerAgreement:
    scheduler: str
    exact: float
    empirical: float
    replicates: int
    radius: float

    @property
    def within_radius(self) -> bool:
        return abs(self.empirical - self.exact) <= self.radius

    def to_dict(self) -> dict[str, float | str | int | bool]:
        return {
            "scheduler": self.scheduler,
            "exact": self.exact,
            "empirical": self.empirical,
            "replicates": self.replicates,
            "radius": self.radius,
            "within_radius": self.within_radius,
        }


def agree_first_passage(
    model: Model,
    predicate: Callable[[Runtime], bool],
    exact: float,
    *,
    event_count: int,
    replicates: int,
    root_seed: int,
    alpha: float = 1e-6,
) -> tuple[SchedulerAgreement, ...]:
    radius = hoeffding_radius(replicates, alpha)
    rows = []
    for scheduler in KERNEL_SCHEDULERS:
        empirical = first_passage_frequency(
            model,
            predicate,
            scheduler=scheduler,
            replicates=replicates,
            root_seed=root_seed,
            event_count=event_count,
        )
        rows.append(
            SchedulerAgreement(
                scheduler=scheduler.value,
                exact=exact,
                empirical=empirical,
                replicates=replicates,
                radius=radius,
            )
        )
    return tuple(rows)


def bits_all_on(runtime: Runtime) -> bool:
    return all(vertex.attributes["on"] for vertex in runtime.graph.vertices.values())


def race_winner_a(runtime: Runtime) -> bool:
    return any(
        vertex.type_id == "Track" and vertex.attributes["winner"] == "a"
        for vertex in runtime.graph.vertices.values()
    )
