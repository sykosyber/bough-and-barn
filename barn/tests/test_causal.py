from barn.causal import why_agent_exists
from barn.engine import BarnEngine
from barn.store import InMemoryGraphStore


async def test_why_path_traces_goal_through_work_capability_request_to_agent():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(goal="Build collaborative editor", command_id="create")
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    sync = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implement realtime sync",
        parent_work_id=root.id,
        required_capabilities={"sync"},
        command_id="sync-work",
    )
    conflict = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Choose conflict-resolution strategy",
        parent_work_id=sync.id,
        required_capabilities={"crdt"},
        command_id="conflict-work",
    )
    decision = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=conflict.id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Sync work exposed an unresolved convergence question.",
        command_id="spawn-crdt",
    )

    explanation = await why_agent_exists(store, run.id, decision.agent_id)

    assert [step.kind for step in explanation.steps] == [
        "work",
        "work",
        "work",
        "capability",
        "request",
        "agent",
    ]
    assert [step.label for step in explanation.steps[:3]] == [
        "Build collaborative editor",
        "Implement realtime sync",
        "Choose conflict-resolution strategy",
    ]
    assert explanation.steps[3].label == "crdt"
    assert "unresolved convergence" in explanation.steps[4].label
    assert explanation.steps[-1].label == "CRDT Specialist"
