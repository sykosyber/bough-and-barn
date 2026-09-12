from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field

from .domain import Agent, Artifact, WorkItem
from .store import GraphStore


class ContextPack(BaseModel):
    """Minimal durable context Barn grants to one logical agent invocation."""

    run_id: str
    agent: Agent
    target_work: WorkItem
    work_items: list[WorkItem] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    workspace_path: str | None = None
    workspace_branch: str | None = None


class AgentResult(BaseModel):
    output: str
    session_id: str | None = None
    total_cost_usd: float | None = None
    total_credits: float | None = None
    num_turns: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentRuntime(Protocol):
    async def run(self, agent: Agent, context: ContextPack) -> AgentResult: ...


async def build_context_pack(
    store: GraphStore,
    *,
    run_id: str,
    agent_id: str,
    work_id: str,
    budget: dict[str, Any] | None = None,
) -> ContextPack:
    """Build a bounded context view from explicit structural relevance only.

    Relevant work is the target, its parent chain, and its explicit dependencies.
    Dependencies are traversed recursively because their own prerequisites may be
    necessary to interpret the target. Artifacts are included only when attached
    to one of those work items. Global event/chat history is deliberately absent.
    """

    state = await store.get_run(run_id)
    try:
        agent = state.agents[agent_id]
    except KeyError as exc:
        raise ValueError("agent_not_found") from exc
    try:
        target = state.work_items[work_id]
    except KeyError as exc:
        raise ValueError("work_not_found") from exc

    relevant: set[str] = set()

    def add_ancestors(current_id: str) -> None:
        cursor = current_id
        seen: set[str] = set()
        while cursor and cursor not in seen:
            seen.add(cursor)
            work = state.work_items.get(cursor)
            if work is None:
                break
            relevant.add(cursor)
            cursor = work.parent_work_id or ""

    def add_dependencies(current_id: str) -> None:
        work = state.work_items.get(current_id)
        if work is None:
            return
        for dependency_id in sorted(work.dependency_ids):
            if dependency_id in relevant:
                continue
            relevant.add(dependency_id)
            add_ancestors(dependency_id)
            add_dependencies(dependency_id)

    add_ancestors(work_id)
    add_dependencies(work_id)

    work_items = sorted(
        (state.work_items[item_id].model_copy(deep=True) for item_id in relevant),
        key=lambda item: (item.created_seq, item.id),
    )
    artifacts = sorted(
        (
            artifact.model_copy(deep=True)
            for artifact in state.artifacts.values()
            if artifact.work_id in relevant
        ),
        key=lambda item: (item.created_seq, item.id),
    )

    return ContextPack(
        run_id=run_id,
        agent=agent.model_copy(deep=True),
        target_work=target.model_copy(deep=True),
        work_items=work_items,
        artifacts=artifacts,
        budget=dict(budget or {}),
    )


class ScriptedRuntime:
    """Deterministic runtime used for tests and offline demonstrations."""

    def __init__(
        self,
        script: Callable[[Agent, ContextPack], AgentResult | Awaitable[AgentResult]],
    ) -> None:
        self.script = script
        self.calls: list[tuple[Agent, ContextPack]] = []

    async def run(self, agent: Agent, context: ContextPack) -> AgentResult:
        self.calls.append((agent.model_copy(deep=True), context.model_copy(deep=True)))
        result = self.script(agent, context)
        if hasattr(result, "__await__"):
            result = await result  # type: ignore[assignment]
        if not isinstance(result, AgentResult):
            raise TypeError("script must return AgentResult")
        return result.model_copy(deep=True)
