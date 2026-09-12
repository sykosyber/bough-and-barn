from datetime import datetime, timedelta, timezone

import pytest

from barn.engine import BarnEngine
from barn.replay import ReplayError, replay_run
from barn.store import InMemoryGraphStore


@pytest.mark.asyncio
async def test_event_log_replays_semantic_run_state_exactly():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Build collaborative editor",
        max_active_agents=4,
        chief_capabilities={"generalist", "architecture"},
        command_id="run",
        run_id="run-replay",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))

    general = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Write architecture note",
        description="Record architecture decisions",
        required_capabilities={"architecture"},
        parent_work_id=root.id,
        priority=2,
        command_id="work-general",
    )
    await engine.assign_work(
        run.id,
        agent_id=chief.id,
        work_id=general.id,
        command_id="assign-general",
    )
    crdt = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Choose CRDT",
        description="Need convergence semantics",
        required_capabilities={"crdt"},
        parent_work_id=general.id,
        requires_verification=True,
        priority=7,
        command_id="work-crdt",
    )
    spawned = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=crdt.id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Architecture exposed a convergence capability gap",
        command_id="spawn",
    )
    rejected = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=crdt.id,
        capability="database",
        role="Database Specialist",
        reason="Not actually required",
        command_id="reject",
    )
    assert rejected.outcome == "rejected"

    started = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)
    ended = started + timedelta(seconds=2.5)
    await engine.record_execution(
        run.id,
        agent_id=spawned.agent_id,
        work_id=crdt.id,
        workspace_path="/tmp/barn/crdt",
        workspace_branch="barn/run-replay/crdt",
        output_summary="Designed an RGA-based merge strategy",
        started_at=started,
        ended_at=ended,
        runtime_session_id="qoder-session",
        total_cost_usd=0.11,
        total_credits=4.5,
        num_turns=3,
        command_id="execution",
    )
    artifact = await engine.submit_artifact(
        run.id,
        agent_id=spawned.agent_id,
        work_id=crdt.id,
        kind="design",
        uri="file://crdt.md",
        content_hash="hash-crdt",
        command_id="artifact",
    )
    await engine.record_verification(
        run.id,
        verifier_agent_id=chief.id,
        artifact_id=artifact.id,
        passed=True,
        evidence="Independent review passed",
        command_id="verification",
    )
    await engine.resolve_work(
        run.id,
        actor_agent_id=spawned.agent_id,
        work_id=crdt.id,
        command_id="resolve",
    )
    await engine.retire_agent(
        run.id,
        agent_id=spawned.agent_id,
        command_id="retire",
    )

    snapshot = await store.get_run(run.id)
    events = await store.list_events(run.id)
    replayed = replay_run(events)

    snapshot.version = 0
    replayed.version = 0
    assert replayed == snapshot


def test_replay_rejects_non_monotonic_event_sequence():
    from barn.domain import BarnEvent

    events = [
        BarnEvent(seq=2, run_id="run", command_id="a", type="run.created", payload={}),
        BarnEvent(seq=1, run_id="run", command_id="b", type="specialist.rejected", payload={}),
    ]

    with pytest.raises(ReplayError, match="event_sequence_invalid"):
        replay_run(events)
