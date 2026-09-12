from __future__ import annotations

from .causal import why_agent_exists
from .engine import BarnEngine, TransitionError


async def bootstrap_demo(engine: BarnEngine) -> dict:
    run = await engine.create_run(
        goal="Build a collaborative markdown editor",
        max_active_agents=4,
        chief_capabilities={"generalist", "architecture"},
        command_id="demo:create",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    sync = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implement realtime synchronization",
        description="The editor must support multiple concurrent writers.",
        required_capabilities={"sync"},
        parent_work_id=root.id,
        command_id="demo:sync",
    )
    conflict = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Choose conflict-resolution strategy",
        description="Realtime synchronization exposed unresolved convergence semantics.",
        required_capabilities={"crdt"},
        parent_work_id=sync.id,
        requires_verification=True,
        command_id="demo:conflict",
    )
    decision = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=conflict.id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Realtime sync exposed an unresolved convergence requirement.",
        command_id="demo:spawn-crdt",
    )
    state = await engine.store.get_run(run.id)
    explanation = await why_agent_exists(engine.store, run.id, decision.agent_id)
    return {
        "state": state.model_dump(mode="json"),
        "decision": decision.model_dump(mode="json"),
        "specialist_why": explanation.model_dump(mode="json"),
    }


async def complete_demo(engine: BarnEngine, run_id: str) -> dict:
    state = await engine.store.get_run(run_id)
    specialist = next(
        (agent for agent in state.agents.values() if agent.role == "CRDT Specialist"),
        None,
    )
    chief = next((agent for agent in state.agents.values() if agent.role == "Chief"), None)
    if specialist is None or chief is None or specialist.spawned_because_work_id is None:
        raise TransitionError("demo_specialist_not_found")
    work_id = specialist.spawned_because_work_id

    artifact = await engine.submit_artifact(
        run_id,
        agent_id=specialist.id,
        work_id=work_id,
        kind="design",
        uri="memory://crdt-strategy.md",
        content_hash="demo-crdt-strategy-v1",
        command_id="demo:artifact-crdt",
    )
    await engine.record_verification(
        run_id,
        verifier_agent_id=chief.id,
        artifact_id=artifact.id,
        passed=True,
        evidence="Independent chief review: strategy defines deterministic merge semantics.",
        command_id="demo:verify-crdt",
    )
    await engine.resolve_work(
        run_id,
        actor_agent_id=specialist.id,
        work_id=work_id,
        command_id="demo:resolve-crdt",
    )
    await engine.retire_agent(
        run_id,
        agent_id=specialist.id,
        command_id="demo:retire-crdt",
    )
    final = await engine.store.get_run(run_id)
    events = await engine.store.list_events(run_id)
    explanation = await why_agent_exists(engine.store, run_id, specialist.id)
    return {
        "state": final.model_dump(mode="json"),
        "events": [event.model_dump(mode="json") for event in events],
        "specialist_why": explanation.model_dump(mode="json"),
    }
