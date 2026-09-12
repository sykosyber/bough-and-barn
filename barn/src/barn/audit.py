from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel

from .domain import RunState
from .replay import ReplayError, replay_run
from .store import GraphStore


class AuditReport(BaseModel):
    run_id: str
    event_count: int
    materialized_hash: str
    replayed_hash: str | None = None
    matches: bool
    replay_error: str | None = None


def canonical_state_payload(state: RunState) -> dict[str, Any]:
    """Return persistence-independent semantic state for hashing.

    ``version`` is a store concurrency counter rather than Barn semantics, so it
    is excluded. Collection ordering is normalized recursively so hashes do not
    depend on Python set/dict insertion order.
    """

    payload = state.model_dump(mode="json")
    payload.pop("version", None)
    return _normalize(payload)


def canonical_state_hash(state: RunState) -> str:
    encoded = json.dumps(
        canonical_state_payload(state),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


async def audit_run(store: GraphStore, run_id: str) -> AuditReport:
    materialized = await store.get_run(run_id)
    events = await store.list_events(run_id)
    materialized_hash = canonical_state_hash(materialized)
    try:
        replayed = replay_run(events)
    except ReplayError as exc:
        return AuditReport(
            run_id=run_id,
            event_count=len(events),
            materialized_hash=materialized_hash,
            replayed_hash=None,
            matches=False,
            replay_error=str(exc),
        )
    replayed_hash = canonical_state_hash(replayed)
    return AuditReport(
        run_id=run_id,
        event_count=len(events),
        materialized_hash=materialized_hash,
        replayed_hash=replayed_hash,
        matches=materialized_hash == replayed_hash,
    )


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        normalized = [_normalize(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        )
    return value
