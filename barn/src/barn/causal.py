from __future__ import annotations

from pydantic import BaseModel

from .store import GraphStore


class CausalStep(BaseModel):
    kind: str
    id: str
    label: str


class AgentExplanation(BaseModel):
    agent_id: str
    steps: list[CausalStep]


async def why_agent_exists(store: GraphStore, run_id: str, agent_id: str) -> AgentExplanation:
    state = await store.get_run(run_id)
    agent = state.agents.get(agent_id)
    if agent is None:
        raise KeyError(agent_id)

    if agent.spawned_because_work_id is None:
        return AgentExplanation(
            agent_id=agent_id,
            steps=[CausalStep(kind="agent", id=agent.id, label=agent.role)],
        )

    work_chain = []
    cursor = state.work_items.get(agent.spawned_because_work_id)
    visited: set[str] = set()
    while cursor is not None:
        if cursor.id in visited:
            raise ValueError("work_parent_cycle")
        visited.add(cursor.id)
        work_chain.append(cursor)
        cursor = state.work_items.get(cursor.parent_work_id) if cursor.parent_work_id else None
    work_chain.reverse()

    capability = next(iter(sorted(agent.capabilities)), "unknown")
    spawn_event = None
    for event in await store.list_events(run_id):
        decision = event.payload.get("decision")
        if event.type == "specialist.spawned" and isinstance(decision, dict):
            if decision.get("agent_id") == agent_id:
                spawn_event = event
                break

    request_label = agent.spawn_reason or "Specialist requested"
    request_id = f"request:{agent_id}"
    if spawn_event is not None:
        request_label = str(spawn_event.payload.get("reason") or request_label)
        request_id = f"event:{spawn_event.seq}"

    steps = [
        CausalStep(kind="work", id=work.id, label=work.title)
        for work in work_chain
    ]
    steps.extend(
        [
            CausalStep(kind="capability", id=f"capability:{capability}", label=capability),
            CausalStep(kind="request", id=request_id, label=request_label),
            CausalStep(kind="agent", id=agent.id, label=agent.role),
        ]
    )
    return AgentExplanation(agent_id=agent_id, steps=steps)
