from barn.engine import BarnEngine, SpecialistOutcome
from barn.store import InMemoryGraphStore


async def _run_with_crdt_need(max_agents: int = 4):
    engine = BarnEngine(InMemoryGraphStore())
    run = await engine.create_run(
        goal="Build a collaborative markdown editor",
        max_active_agents=max_agents,
        chief_capabilities={"generalist", "architecture"},
        command_id="create-run",
    )
    chief = next(iter(run.agents.values()))
    work = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Choose conflict-resolution strategy",
        description="Realtime sync requires an explicit convergence strategy.",
        required_capabilities={"crdt"},
        parent_work_id=next(iter(run.work_items.values())).id,
        command_id="add-crdt-work",
    )
    return engine, run.id, chief.id, work.id


async def test_explicit_capability_gap_licenses_specialist_and_binds_cause():
    engine, run_id, chief_id, work_id = await _run_with_crdt_need()

    decision = await engine.request_specialist(
        run_id,
        requesting_agent_id=chief_id,
        work_id=work_id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Conflict resolution is unresolved and requires CRDT expertise.",
        command_id="spawn-crdt",
    )

    assert decision.outcome is SpecialistOutcome.SPAWNED
    state = await engine.store.get_run(run_id)
    specialist = state.agents[decision.agent_id]
    assert specialist.capabilities == {"crdt"}
    assert specialist.parent_agent_id == chief_id
    assert specialist.spawned_because_work_id == work_id
    assert specialist.spawn_reason.startswith("Conflict resolution")
    assert state.work_items[work_id].assigned_agent_id == specialist.id


async def test_existing_idle_compatible_agent_is_reused_instead_of_spawning_duplicate():
    engine, run_id, chief_id, work_id = await _run_with_crdt_need()
    first = await engine.request_specialist(
        run_id,
        requesting_agent_id=chief_id,
        work_id=work_id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Need CRDT expertise.",
        command_id="spawn-first",
    )
    artifact = await engine.submit_artifact(
        run_id,
        agent_id=first.agent_id,
        work_id=work_id,
        kind="design",
        uri="memory://first",
        content_hash="first",
        command_id="artifact-first",
    )
    assert artifact.work_id == work_id
    await engine.resolve_work(
        run_id,
        actor_agent_id=first.agent_id,
        work_id=work_id,
        command_id="resolve-first",
    )
    second_work = await engine.add_work(
        run_id,
        actor_agent_id=chief_id,
        title="Review sync merge semantics",
        required_capabilities={"crdt"},
        command_id="add-second-crdt-work",
    )

    second = await engine.request_specialist(
        run_id,
        requesting_agent_id=chief_id,
        work_id=second_work.id,
        capability="crdt",
        role="Another CRDT Specialist",
        reason="Need another CRDT check.",
        command_id="request-second",
    )

    assert second.outcome is SpecialistOutcome.REUSED
    assert second.agent_id == first.agent_id
    state = await engine.store.get_run(run_id)
    assert len(state.agents) == 2


async def test_busy_compatible_specialist_is_not_reused_for_conflicting_work():
    engine, run_id, chief_id, work_id = await _run_with_crdt_need()
    first = await engine.request_specialist(
        run_id,
        requesting_agent_id=chief_id,
        work_id=work_id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Need CRDT expertise.",
        command_id="spawn-first",
    )
    second_work = await engine.add_work(
        run_id,
        actor_agent_id=chief_id,
        title="Independent CRDT migration",
        required_capabilities={"crdt"},
        command_id="add-second-crdt-work",
    )

    second = await engine.request_specialist(
        run_id,
        requesting_agent_id=chief_id,
        work_id=second_work.id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Independent work should not overload the first specialist.",
        command_id="request-second",
    )

    assert second.outcome is SpecialistOutcome.SPAWNED
    assert second.agent_id != first.agent_id
    state = await engine.store.get_run(run_id)
    assert len(state.agents) == 3


async def test_spawn_is_rejected_when_capability_is_not_required_by_work():
    engine, run_id, chief_id, work_id = await _run_with_crdt_need()

    decision = await engine.request_specialist(
        run_id,
        requesting_agent_id=chief_id,
        work_id=work_id,
        capability="database",
        role="Database Specialist",
        reason="Maybe useful.",
        command_id="bad-capability",
    )

    assert decision.outcome is SpecialistOutcome.REJECTED
    assert decision.reason == "capability_not_required"


async def test_spawn_is_rejected_at_active_agent_budget():
    engine, run_id, chief_id, work_id = await _run_with_crdt_need(max_agents=1)

    decision = await engine.request_specialist(
        run_id,
        requesting_agent_id=chief_id,
        work_id=work_id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Need CRDT expertise.",
        command_id="over-budget",
    )

    assert decision.outcome is SpecialistOutcome.REJECTED
    assert decision.reason == "active_agent_budget_exhausted"


async def test_retrying_same_spawn_command_does_not_create_second_agent():
    engine, run_id, chief_id, work_id = await _run_with_crdt_need()
    kwargs = dict(
        run_id=run_id,
        requesting_agent_id=chief_id,
        work_id=work_id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Need CRDT expertise.",
        command_id="same-command",
    )

    first = await engine.request_specialist(**kwargs)
    second = await engine.request_specialist(**kwargs)

    assert second == first
    state = await engine.store.get_run(run_id)
    assert len(state.agents) == 2
