from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from .domain import AgentStatus, BarnEvent, RunState, WorkStatus


class RunMetrics(BaseModel):
    agent_total: int = 0
    agent_active: int = 0
    agent_idle: int = 0
    agent_retired: int = 0
    work_total: int = 0
    work_by_status: dict[str, int] = Field(default_factory=dict)
    artifact_count: int = 0
    verification_count: int = 0
    specialist_spawned: int = 0
    specialist_reused: int = 0
    specialist_rejected: int = 0
    runtime_executions: int = 0
    runtime_cost_usd_total: float = 0.0
    runtime_credits_total: float = 0.0
    runtime_turns_total: int = 0
    runtime_seconds_total: float = 0.0


def summarize_run(state: RunState, events: list[BarnEvent]) -> RunMetrics:
    agent_counts = Counter(agent.status.value for agent in state.agents.values())
    work_counts = Counter(work.status.value for work in state.work_items.values())
    event_counts = Counter(event.type for event in events)

    executions = list(state.executions.values())
    return RunMetrics(
        agent_total=len(state.agents),
        agent_active=agent_counts[AgentStatus.ACTIVE.value],
        agent_idle=agent_counts[AgentStatus.IDLE.value],
        agent_retired=agent_counts[AgentStatus.RETIRED.value],
        work_total=len(state.work_items),
        work_by_status={status.value: work_counts[status.value] for status in WorkStatus},
        artifact_count=len(state.artifacts),
        verification_count=len(state.verifications),
        specialist_spawned=event_counts["specialist.spawned"],
        specialist_reused=event_counts["specialist.reused"],
        specialist_rejected=event_counts["specialist.rejected"],
        runtime_executions=len(executions),
        runtime_cost_usd_total=sum(item.total_cost_usd or 0.0 for item in executions),
        runtime_credits_total=sum(item.total_credits or 0.0 for item in executions),
        runtime_turns_total=sum(item.num_turns or 0 for item in executions),
        runtime_seconds_total=sum(item.duration_seconds for item in executions),
    )
