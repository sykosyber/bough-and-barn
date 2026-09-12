"""Chance/decision split. Kernel schedulers never see decision rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from osahr.pattern import Rule

from bough.errors import BoughRefusal


class EventKind(str, Enum):
    CHANCE = "chance"
    DECISION = "decision"


@dataclass(frozen=True, slots=True)
class EventSpec:
    event_id: str
    kind: EventKind
    rule: Rule


def validate_event(spec: EventSpec) -> None:
    names = spec.rule.hazard.names
    if spec.kind is EventKind.CHANCE:
        if "time" in names:
            raise BoughRefusal(
                "TIME_VARYING_HAZARD",
                f"{spec.event_id} hazard depends on absolute time",
            )
        if spec.rule.adaptation:
            raise BoughRefusal(
                "ADAPTIVE_ASSIGNMENTS",
                f"{spec.event_id} has adaptive assignments; Theta would be path-dependent",
            )
    elif spec.kind is EventKind.DECISION:
        if spec.rule.hazard.source.strip() not in {"0", "0.0"}:
            raise BoughRefusal(
                "DECISION_WITH_HAZARD",
                f"{spec.event_id} is a decision and must not carry a real hazard",
            )
        if spec.rule.adaptation:
            raise BoughRefusal(
                "ADAPTIVE_ASSIGNMENTS",
                f"{spec.event_id} has adaptive assignments",
            )


def require_chance_has_hazard(event_id: str, hazard_source: str | None) -> None:
    if hazard_source is None:
        raise BoughRefusal("CHANCE_WITHOUT_HAZARD", f"{event_id} is chance with no hazard")
