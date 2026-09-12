from barn.engine import BarnEngine
from barn.scheduler import BarnScheduler
from barn.store import InMemoryGraphStore


async def test_dependencies_gate_ready_work_then_release_it_after_resolution():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    scheduler = BarnScheduler(store)
    run = await engine.create_run(goal="Goal", command_id="create")
    chief = next(iter(run.agents.values()))
    first = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Architecture",
        command_id="first",
        priority=1,
    )
    second = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implementation",
        dependency_ids={first.id},
        command_id="second",
        priority=10,
    )

    ready_before = await scheduler.ready_work(run.id)
    assert [item.id for item in ready_before] == [first.id]

    await engine.submit_artifact(
        run.id,
        agent_id=chief.id,
        work_id=first.id,
        kind="architecture",
        uri="artifact://architecture",
        content_hash="arch",
        command_id="artifact-first",
    )
    await engine.resolve_work(
        run.id,
        actor_agent_id=chief.id,
        work_id=first.id,
        command_id="resolve-first",
    )

    ready_after = await scheduler.ready_work(run.id)
    assert [item.id for item in ready_after] == [second.id]


async def test_ready_work_orders_by_priority_then_creation_sequence():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    scheduler = BarnScheduler(store)
    run = await engine.create_run(goal="Goal", command_id="create")
    chief = next(iter(run.agents.values()))
    low = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Low",
        command_id="low",
        priority=1,
    )
    high_a = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="High A",
        command_id="high-a",
        priority=5,
    )
    high_b = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="High B",
        command_id="high-b",
        priority=5,
    )

    ready = await scheduler.ready_work(run.id)
    assert [item.id for item in ready] == [high_a.id, high_b.id, low.id]


async def test_compatible_agents_excludes_busy_specialist_but_keeps_chief_available():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    scheduler = BarnScheduler(store)
    run = await engine.create_run(
        goal="Goal",
        chief_capabilities={"generalist", "crdt"},
        command_id="create",
    )
    chief = next(iter(run.agents.values()))
    first = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="CRDT A",
        required_capabilities={"crdt"},
        command_id="first",
    )
    # Because Chief already has CRDT, request_specialist would reuse Chief. Force a specialist
    # by creating one through a different capability and then expanding its declared capability.
    specialist_work = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Specialist setup",
        required_capabilities={"sync"},
        command_id="specialist-work",
    )
    spawned = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=specialist_work.id,
        capability="sync",
        role="Sync Specialist",
        reason="Need sync",
        command_id="spawn",
    )
    state = await store.get_run(run.id)
    state.agents[spawned.agent_id].capabilities.add("crdt")
    await store.save_run(state, expected_version=state.version)

    compatible = await scheduler.compatible_agents(run.id, first.id)
    compatible_ids = [agent.id for agent in compatible]

    assert chief.id in compatible_ids
    assert spawned.agent_id not in compatible_ids
