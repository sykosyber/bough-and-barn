import pytest

from barn.audit import audit_run, canonical_state_hash
from barn.engine import BarnEngine
from barn.store import InMemoryGraphStore


@pytest.mark.asyncio
async def test_audit_matches_materialized_state_to_event_replay():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    state = await engine.create_run(
        goal="Build parser",
        chief_capabilities={"python"},
        command_id="run",
        run_id="run-audit",
    )
    chief = next(iter(state.agents.values()))
    root = next(iter(state.work_items.values()))
    await engine.add_work(
        state.id,
        actor_agent_id=chief.id,
        title="Implement tokenizer",
        parent_work_id=root.id,
        command_id="work",
    )

    report = await audit_run(store, state.id)

    assert report.matches is True
    assert report.event_count == 2
    assert report.materialized_hash == report.replayed_hash
    assert report.replay_error is None


@pytest.mark.asyncio
async def test_audit_detects_materialized_state_divergence_without_event():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    state = await engine.create_run(
        goal="Build parser",
        chief_capabilities={"python"},
        command_id="run",
        run_id="run-audit-diverged",
    )
    mutated = await store.get_run(state.id)
    chief = next(iter(mutated.agents.values()))
    chief.capabilities.add("unlicensed-capability")
    await store.save_run(mutated, expected_version=mutated.version)

    report = await audit_run(store, state.id)

    assert report.matches is False
    assert report.materialized_hash != report.replayed_hash


def test_canonical_hash_ignores_store_version_but_not_semantic_state():
    from barn.domain import RunState

    first = RunState(id="run", goal="Goal", version=1)
    second = first.model_copy(deep=True)
    second.version = 99
    assert canonical_state_hash(first) == canonical_state_hash(second)

    second.goal = "Different goal"
    assert canonical_state_hash(first) != canonical_state_hash(second)
