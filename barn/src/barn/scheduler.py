from __future__ import annotations

from .domain import Agent, AgentStatus, WorkItem, WorkStatus
from .store import GraphStore


class BarnScheduler:
    def __init__(self, store: GraphStore) -> None:
        self.store = store

    async def ready_work(self, run_id: str) -> list[WorkItem]:
        state = await self.store.get_run(run_id)
        candidates: list[WorkItem] = []
        for work in state.work_items.values():
            if work.status in {WorkStatus.RESOLVED, WorkStatus.CANCELLED, WorkStatus.ACTIVE, WorkStatus.REVIEW}:
                continue
            if work.assigned_agent_id is not None:
                continue
            if not all(
                dependency_id in state.work_items
                and state.work_items[dependency_id].status == WorkStatus.RESOLVED
                for dependency_id in work.dependency_ids
            ):
                continue
            candidates.append(work)
        return sorted(candidates, key=lambda item: (-item.priority, item.created_seq, item.id))

    async def compatible_agents(self, run_id: str, work_id: str) -> list[Agent]:
        state = await self.store.get_run(run_id)
        work = state.work_items[work_id]
        def available(agent: Agent) -> bool:
            if agent.status == AgentStatus.RETIRED:
                return False
            if not work.required_capabilities.issubset(agent.capabilities):
                return False
            if agent.role == "Chief":
                return True
            return not any(
                assigned_id != work_id
                and assigned_id in state.work_items
                and state.work_items[assigned_id].status not in {WorkStatus.RESOLVED, WorkStatus.CANCELLED}
                for assigned_id in agent.assigned_work_ids
            )

        agents = [agent for agent in state.agents.values() if available(agent)]
        return sorted(agents, key=lambda item: (item.created_seq, item.id))
