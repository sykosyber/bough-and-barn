from barn.domain import BarnEvent, RunState
from barn.store import InMemoryGraphStore


async def test_append_event_is_idempotent_by_command_id():
    store = InMemoryGraphStore()
    await store.create_run(RunState(id="run-1", goal="Build a collaborative editor", max_active_agents=4))

    first = await store.append_event(
        BarnEvent(run_id="run-1", command_id="c1", type="run.created", payload={})
    )
    second = await store.append_event(
        BarnEvent(run_id="run-1", command_id="c1", type="run.created", payload={"ignored": True})
    )

    assert first.seq == 1
    assert second == first
    assert [event.seq for event in await store.list_events("run-1")] == [1]


async def test_event_sequence_is_monotonic_per_run():
    store = InMemoryGraphStore()
    await store.create_run(RunState(id="run-1", goal="Goal", max_active_agents=4))

    events = []
    for index in range(3):
        events.append(
            await store.append_event(
                BarnEvent(
                    run_id="run-1",
                    command_id=f"c{index}",
                    type="test.event",
                    payload={"index": index},
                )
            )
        )

    assert [event.seq for event in events] == [1, 2, 3]


async def test_snapshot_returns_copy_not_mutable_internal_state():
    store = InMemoryGraphStore()
    await store.create_run(RunState(id="run-1", goal="Goal", max_active_agents=4))

    snapshot = await store.get_run("run-1")
    snapshot.goal = "mutated"

    fresh = await store.get_run("run-1")
    assert fresh.goal == "Goal"
