import pytest

from barn.domain import AgentStatus, WorkStatus
from barn.engine import BarnEngine, TransitionError
from barn.store import InMemoryGraphStore


@pytest.mark.asyncio
async def test_idle_compatible_agent_can_be_explicitly_assigned_ready_work():
    engine = BarnEngine(InMemoryGraphStore())
    run = await engine.create_run(
        goal="Build editor",
        chief_capabilities={"generalist"},
        command_id="run",
        run_id="run-assign",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    first_work = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Initial schema",
        required_capabilities={"database"},
        parent_work_id=root.id,
        command_id="first-work",
    )
    spawned = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=first_work.id,
        capability="database",
        role="Database Specialist",
        reason="Schema work needs database capability",
        command_id="spawn-db",
    )
    artifact = await engine.submit_artifact(
        run.id,
        agent_id=spawned.agent_id,
        work_id=first_work.id,
        kind="schema",
        uri="memory://schema",
        content_hash="schema-v1",
        command_id="artifact",
    )
    assert artifact.work_id == first_work.id
    await engine.resolve_work(
        run.id,
        actor_agent_id=spawned.agent_id,
        work_id=first_work.id,
        command_id="resolve",
    )
    second = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Index design",
        required_capabilities={"database"},
        parent_work_id=root.id,
        command_id="second-work",
    )

    assigned = await engine.assign_work(
        run.id,
        agent_id=spawned.agent_id,
        work_id=second.id,
        command_id="assign-second",
    )

    assert assigned.assigned_agent_id == spawned.agent_id
    assert assigned.status == WorkStatus.ACTIVE
    state = await engine.store.get_run(run.id)
    assert state.agents[spawned.agent_id].status == AgentStatus.ACTIVE
    assert second.id in state.agents[spawned.agent_id].assigned_work_ids


@pytest.mark.asyncio
async def test_assignment_rejects_agent_missing_required_capability():
    engine = BarnEngine(InMemoryGraphStore())
    run = await engine.create_run(
        goal="Build editor",
        chief_capabilities={"generalist"},
        command_id="run",
        run_id="run-bad-assign",
    )
    chief = next(iter(run.agents.values()))
    work = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="CRDT design",
        required_capabilities={"crdt"},
        command_id="work",
    )

    with pytest.raises(TransitionError, match="agent_missing_required_capability"):
        await engine.assign_work(
            run.id,
            agent_id=chief.id,
            work_id=work.id,
            command_id="assign",
        )
