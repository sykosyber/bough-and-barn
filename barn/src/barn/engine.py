from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel

from .domain import (
    Agent,
    AgentStatus,
    Artifact,
    BarnEvent,
    ExecutionRecord,
    RunState,
    Verification,
    WorkItem,
    WorkStatus,
)
from .store import GraphStore


class SpecialistOutcome(StrEnum):
    SPAWNED = "spawned"
    REUSED = "reused"
    REJECTED = "rejected"


class SpecialistDecision(BaseModel):
    outcome: SpecialistOutcome
    agent_id: str | None = None
    reason: str
    work_id: str
    capability: str


class TransitionError(ValueError):
    pass


_TERMINAL_WORK = {WorkStatus.RESOLVED, WorkStatus.CANCELLED}


def _agent_has_conflicting_work(state: RunState, agent: Agent, target_work_id: str) -> bool:
    if agent.role == "Chief":
        return False
    return any(
        assigned_id != target_work_id
        and assigned_id in state.work_items
        and state.work_items[assigned_id].status not in _TERMINAL_WORK
        for assigned_id in agent.assigned_work_ids
    )


class BarnEngine:
    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, run_id: str) -> asyncio.Lock:
        return self._locks.setdefault(run_id, asyncio.Lock())

    @staticmethod
    def _id(prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:12]}"

    async def create_run(
        self,
        *,
        goal: str,
        max_active_agents: int = 6,
        chief_capabilities: set[str] | None = None,
        command_id: str,
        run_id: str | None = None,
    ) -> RunState:
        run_id = run_id or self._id("run")
        chief_id = self._id("agent")
        goal_work_id = self._id("work")
        capabilities = chief_capabilities or {"generalist"}
        created_at = datetime.now(timezone.utc)
        chief = Agent(
            id=chief_id,
            run_id=run_id,
            role="Chief",
            capabilities=capabilities,
            assigned_work_ids={goal_work_id},
            created_seq=1,
        )
        goal_work = WorkItem(
            id=goal_work_id,
            run_id=run_id,
            title=goal,
            description="Root goal",
            status=WorkStatus.ACTIVE,
            required_capabilities=set(),
            assigned_agent_id=chief_id,
            created_seq=1,
        )
        state = RunState(
            id=run_id,
            goal=goal,
            max_active_agents=max_active_agents,
            agents={chief.id: chief},
            work_items={goal_work.id: goal_work},
            created_at=created_at,
        )
        await self.store.create_run(state)
        await self.store.append_event(
            BarnEvent(
                run_id=run_id,
                command_id=command_id,
                type="run.created",
                actor_agent_id=chief_id,
                work_id=goal_work_id,
                payload={
                    "goal": goal,
                    "max_active_agents": max_active_agents,
                    "chief_agent_id": chief_id,
                    "chief_capabilities": sorted(capabilities),
                    "goal_work_id": goal_work_id,
                },
                created_at=created_at,
            )
        )
        return await self.store.get_run(run_id)

    async def add_work(
        self,
        run_id: str,
        *,
        actor_agent_id: str,
        title: str,
        command_id: str,
        description: str = "",
        required_capabilities: set[str] | None = None,
        parent_work_id: str | None = None,
        dependency_ids: set[str] | None = None,
        requires_verification: bool = False,
        priority: int = 0,
    ) -> WorkItem:
        async with self._lock(run_id):
            existing = await self.store.get_event_by_command(run_id, command_id)
            if existing is not None:
                work_id = existing.payload.get("work_id")
                state = await self.store.get_run(run_id)
                if work_id and work_id in state.work_items:
                    return state.work_items[work_id]
                raise TransitionError("idempotent work event no longer references existing work")

            state = await self.store.get_run(run_id)
            if actor_agent_id not in state.agents:
                raise TransitionError("actor_agent_not_found")
            if parent_work_id is not None and parent_work_id not in state.work_items:
                raise TransitionError("parent_work_not_found")
            dependencies = dependency_ids or set()
            if not dependencies.issubset(state.work_items):
                raise TransitionError("dependency_not_found")
            ready = all(state.work_items[dep].status == WorkStatus.RESOLVED for dep in dependencies)
            work_id = self._id("work")
            event = await self.store.append_event(
                BarnEvent(
                    run_id=run_id,
                    command_id=command_id,
                    type="work.created",
                    actor_agent_id=actor_agent_id,
                    work_id=work_id,
                    payload={
                        "work_id": work_id,
                        "title": title,
                        "description": description,
                        "status": (WorkStatus.READY if ready else WorkStatus.BLOCKED).value,
                        "required_capabilities": sorted(required_capabilities or set()),
                        "parent_work_id": parent_work_id,
                        "dependency_ids": sorted(dependencies),
                        "requires_verification": requires_verification,
                        "priority": priority,
                    },
                )
            )
            work = WorkItem(
                id=work_id,
                run_id=run_id,
                title=title,
                description=description,
                status=WorkStatus.READY if ready else WorkStatus.BLOCKED,
                required_capabilities=required_capabilities or set(),
                parent_work_id=parent_work_id,
                dependency_ids=dependencies,
                requires_verification=requires_verification,
                priority=priority,
                created_seq=event.seq,
            )
            state.work_items[work_id] = work
            await self.store.save_run(state, expected_version=state.version)
            return work.model_copy(deep=True)

    async def assign_work(
        self,
        run_id: str,
        *,
        agent_id: str,
        work_id: str,
        command_id: str,
    ) -> WorkItem:
        async with self._lock(run_id):
            existing = await self.store.get_event_by_command(run_id, command_id)
            if existing is not None:
                existing_work_id = existing.payload.get("work_id", work_id)
                state = await self.store.get_run(run_id)
                work = state.work_items.get(existing_work_id)
                if work is None:
                    raise TransitionError("idempotent assignment event missing work")
                return work.model_copy(deep=True)

            state = await self.store.get_run(run_id)
            agent = state.agents.get(agent_id)
            work = state.work_items.get(work_id)
            if agent is None or agent.status == AgentStatus.RETIRED:
                raise TransitionError("agent_unavailable")
            if work is None:
                raise TransitionError("work_not_found")
            if work.status in _TERMINAL_WORK:
                raise TransitionError("work_terminal")
            if not work.required_capabilities.issubset(agent.capabilities):
                raise TransitionError("agent_missing_required_capability")
            if any(
                state.work_items.get(dependency_id) is None
                or state.work_items[dependency_id].status != WorkStatus.RESOLVED
                for dependency_id in work.dependency_ids
            ):
                raise TransitionError("work_dependencies_unresolved")
            if work.assigned_agent_id is not None and work.assigned_agent_id != agent_id:
                raise TransitionError("work_assigned_to_different_agent")
            if _agent_has_conflicting_work(state, agent, work_id):
                raise TransitionError("agent_busy")

            event = await self.store.append_event(
                BarnEvent(
                    run_id=run_id,
                    command_id=command_id,
                    type="work.assigned",
                    actor_agent_id=agent_id,
                    work_id=work_id,
                    payload={"work_id": work_id, "agent_id": agent_id},
                )
            )
            del event
            work.assigned_agent_id = agent_id
            work.status = WorkStatus.ACTIVE
            agent.assigned_work_ids.add(work_id)
            agent.status = AgentStatus.ACTIVE
            await self.store.save_run(state, expected_version=state.version)
            return work.model_copy(deep=True)

    async def request_specialist(
        self,
        run_id: str,
        *,
        requesting_agent_id: str,
        work_id: str,
        capability: str,
        role: str,
        reason: str,
        command_id: str,
    ) -> SpecialistDecision:
        async with self._lock(run_id):
            existing = await self.store.get_event_by_command(run_id, command_id)
            if existing is not None:
                decision_payload = existing.payload.get("decision")
                if decision_payload is None:
                    raise TransitionError("idempotent specialist event missing decision")
                return SpecialistDecision.model_validate(decision_payload)

            state = await self.store.get_run(run_id)
            requester = state.agents.get(requesting_agent_id)
            if requester is None or requester.status == AgentStatus.RETIRED:
                return await self._record_specialist_rejection(
                    state,
                    command_id=command_id,
                    requester_id=requesting_agent_id,
                    work_id=work_id,
                    capability=capability,
                    reason="requesting_agent_unavailable",
                )
            work = state.work_items.get(work_id)
            if work is None:
                return await self._record_specialist_rejection(
                    state,
                    command_id=command_id,
                    requester_id=requesting_agent_id,
                    work_id=work_id,
                    capability=capability,
                    reason="work_not_found",
                )
            if work.status in _TERMINAL_WORK:
                return await self._record_specialist_rejection(
                    state,
                    command_id=command_id,
                    requester_id=requesting_agent_id,
                    work_id=work_id,
                    capability=capability,
                    reason="work_terminal",
                )
            if capability not in work.required_capabilities:
                return await self._record_specialist_rejection(
                    state,
                    command_id=command_id,
                    requester_id=requesting_agent_id,
                    work_id=work_id,
                    capability=capability,
                    reason="capability_not_required",
                )

            reusable = next(
                (
                    agent
                    for agent in sorted(state.agents.values(), key=lambda item: (item.created_seq, item.id))
                    if agent.status != AgentStatus.RETIRED
                    and capability in agent.capabilities
                    and not _agent_has_conflicting_work(state, agent, work_id)
                ),
                None,
            )
            if reusable is not None:
                reusable.assigned_work_ids.add(work_id)
                reusable.status = AgentStatus.ACTIVE
                work.assigned_agent_id = reusable.id
                if work.status == WorkStatus.READY:
                    work.status = WorkStatus.ACTIVE
                decision = SpecialistDecision(
                    outcome=SpecialistOutcome.REUSED,
                    agent_id=reusable.id,
                    reason="existing_compatible_agent",
                    work_id=work_id,
                    capability=capability,
                )
                await self._commit_decision_event(
                    state,
                    command_id=command_id,
                    requester_id=requesting_agent_id,
                    work_id=work_id,
                    event_type="specialist.reused",
                    decision=decision,
                )
                return decision

            active_count = sum(agent.status != AgentStatus.RETIRED for agent in state.agents.values())
            if active_count >= state.max_active_agents:
                return await self._record_specialist_rejection(
                    state,
                    command_id=command_id,
                    requester_id=requesting_agent_id,
                    work_id=work_id,
                    capability=capability,
                    reason="active_agent_budget_exhausted",
                )

            agent_id = self._id("agent")
            decision = SpecialistDecision(
                outcome=SpecialistOutcome.SPAWNED,
                agent_id=agent_id,
                reason="capability_gap_licensed",
                work_id=work_id,
                capability=capability,
            )
            event = await self.store.append_event(
                BarnEvent(
                    run_id=run_id,
                    command_id=command_id,
                    type="specialist.spawned",
                    actor_agent_id=requesting_agent_id,
                    work_id=work_id,
                    payload={"decision": decision.model_dump(mode="json"), "role": role, "reason": reason},
                )
            )
            specialist = Agent(
                id=agent_id,
                run_id=run_id,
                role=role,
                capabilities={capability},
                status=AgentStatus.ACTIVE,
                parent_agent_id=requesting_agent_id,
                spawned_because_work_id=work_id,
                spawn_reason=reason,
                assigned_work_ids={work_id},
                created_seq=event.seq,
            )
            state.agents[agent_id] = specialist
            work.assigned_agent_id = agent_id
            if work.status == WorkStatus.READY:
                work.status = WorkStatus.ACTIVE
            await self.store.save_run(state, expected_version=state.version)
            return decision

    async def submit_artifact(
        self,
        run_id: str,
        *,
        agent_id: str,
        work_id: str,
        kind: str,
        uri: str,
        content_hash: str,
        command_id: str,
    ) -> Artifact:
        async with self._lock(run_id):
            existing = await self.store.get_event_by_command(run_id, command_id)
            if existing is not None:
                artifact_id = existing.payload.get("artifact_id")
                state = await self.store.get_run(run_id)
                if artifact_id and artifact_id in state.artifacts:
                    return state.artifacts[artifact_id]
                raise TransitionError("idempotent artifact event missing artifact")

            state = await self.store.get_run(run_id)
            agent = state.agents.get(agent_id)
            work = state.work_items.get(work_id)
            if agent is None or agent.status == AgentStatus.RETIRED:
                raise TransitionError("producer_agent_unavailable")
            if work is None:
                raise TransitionError("work_not_found")
            if work.status in _TERMINAL_WORK:
                raise TransitionError("work_terminal")
            if work.assigned_agent_id is not None and work.assigned_agent_id != agent_id:
                raise TransitionError("work_assigned_to_different_agent")

            artifact_id = self._id("artifact")
            event = await self.store.append_event(
                BarnEvent(
                    run_id=run_id,
                    command_id=command_id,
                    type="artifact.submitted",
                    actor_agent_id=agent_id,
                    work_id=work_id,
                    payload={
                        "artifact_id": artifact_id,
                        "kind": kind,
                        "uri": uri,
                        "content_hash": content_hash,
                    },
                )
            )
            artifact = Artifact(
                id=artifact_id,
                run_id=run_id,
                work_id=work_id,
                producer_agent_id=agent_id,
                kind=kind,
                uri=uri,
                content_hash=content_hash,
                created_seq=event.seq,
            )
            state.artifacts[artifact_id] = artifact
            if work.status == WorkStatus.ACTIVE:
                work.status = WorkStatus.REVIEW
            await self.store.save_run(state, expected_version=state.version)
            return artifact.model_copy(deep=True)

    async def record_verification(
        self,
        run_id: str,
        *,
        verifier_agent_id: str,
        artifact_id: str,
        passed: bool,
        evidence: str,
        command_id: str,
    ) -> Verification:
        async with self._lock(run_id):
            existing = await self.store.get_event_by_command(run_id, command_id)
            if existing is not None:
                verification_id = existing.payload.get("verification_id")
                state = await self.store.get_run(run_id)
                if verification_id and verification_id in state.verifications:
                    return state.verifications[verification_id]
                raise TransitionError("idempotent verification event missing verification")

            state = await self.store.get_run(run_id)
            verifier = state.agents.get(verifier_agent_id)
            artifact = state.artifacts.get(artifact_id)
            if verifier is None or verifier.status == AgentStatus.RETIRED:
                raise TransitionError("verifier_agent_unavailable")
            if artifact is None:
                raise TransitionError("artifact_not_found")
            if artifact.producer_agent_id == verifier_agent_id:
                raise TransitionError("independent_verifier_required")

            verification_id = self._id("verification")
            event = await self.store.append_event(
                BarnEvent(
                    run_id=run_id,
                    command_id=command_id,
                    type="artifact.verified",
                    actor_agent_id=verifier_agent_id,
                    work_id=artifact.work_id,
                    payload={
                        "verification_id": verification_id,
                        "artifact_id": artifact_id,
                        "passed": passed,
                        "evidence": evidence,
                    },
                )
            )
            verification = Verification(
                id=verification_id,
                run_id=run_id,
                artifact_id=artifact_id,
                verifier_agent_id=verifier_agent_id,
                passed=passed,
                evidence=evidence,
                created_seq=event.seq,
            )
            state.verifications[verification_id] = verification
            await self.store.save_run(state, expected_version=state.version)
            return verification.model_copy(deep=True)

    async def resolve_work(
        self,
        run_id: str,
        *,
        actor_agent_id: str,
        work_id: str,
        command_id: str,
    ) -> WorkItem:
        async with self._lock(run_id):
            existing = await self.store.get_event_by_command(run_id, command_id)
            if existing is not None:
                state = await self.store.get_run(run_id)
                work = state.work_items.get(work_id)
                if work is None:
                    raise TransitionError("work_not_found")
                return work

            state = await self.store.get_run(run_id)
            actor = state.agents.get(actor_agent_id)
            work = state.work_items.get(work_id)
            if actor is None or actor.status == AgentStatus.RETIRED:
                raise TransitionError("actor_agent_unavailable")
            if work is None:
                raise TransitionError("work_not_found")
            if work.status == WorkStatus.RESOLVED:
                return work.model_copy(deep=True)
            if work.assigned_agent_id is not None and work.assigned_agent_id != actor_agent_id:
                raise TransitionError("work_assigned_to_different_agent")

            artifacts = [artifact for artifact in state.artifacts.values() if artifact.work_id == work_id]
            if not artifacts:
                raise TransitionError("artifact_required")
            if work.requires_verification:
                artifact_ids = {artifact.id for artifact in artifacts}
                has_passing = any(
                    verification.passed and verification.artifact_id in artifact_ids
                    for verification in state.verifications.values()
                )
                if not has_passing:
                    raise TransitionError("passing_verification_required")

            event = await self.store.append_event(
                BarnEvent(
                    run_id=run_id,
                    command_id=command_id,
                    type="work.resolved",
                    actor_agent_id=actor_agent_id,
                    work_id=work_id,
                    payload={"artifact_ids": [artifact.id for artifact in artifacts]},
                )
            )
            work.status = WorkStatus.RESOLVED
            work.resolved_seq = event.seq
            if work.assigned_agent_id is not None:
                assigned = state.agents[work.assigned_agent_id]
                assigned.assigned_work_ids.discard(work_id)
                if not assigned.assigned_work_ids:
                    assigned.status = AgentStatus.IDLE
            await self.store.save_run(state, expected_version=state.version)
            return work.model_copy(deep=True)

    async def record_execution(
        self,
        run_id: str,
        *,
        agent_id: str,
        work_id: str,
        workspace_path: str,
        workspace_branch: str,
        output_summary: str,
        started_at,
        ended_at,
        runtime_session_id: str | None,
        total_cost_usd: float | None,
        total_credits: float | None,
        num_turns: int | None,
        command_id: str,
    ) -> ExecutionRecord:
        async with self._lock(run_id):
            existing = await self.store.get_event_by_command(run_id, command_id)
            if existing is not None:
                state = await self.store.get_run(run_id)
                execution_id = existing.payload.get("execution_id")
                if execution_id and execution_id in state.executions:
                    return state.executions[execution_id].model_copy(deep=True)
                raise TransitionError("idempotent execution event missing execution")

            state = await self.store.get_run(run_id)
            agent = state.agents.get(agent_id)
            work = state.work_items.get(work_id)
            if agent is None or agent.status == AgentStatus.RETIRED:
                raise TransitionError("agent_unavailable")
            if work is None:
                raise TransitionError("work_not_found")
            if work.status in _TERMINAL_WORK:
                raise TransitionError("work_terminal")
            if work.assigned_agent_id != agent_id:
                raise TransitionError("work_not_assigned_to_agent")
            if ended_at < started_at:
                raise TransitionError("execution_time_invalid")

            execution_id = self._id("execution")
            event = await self.store.append_event(
                BarnEvent(
                    run_id=run_id,
                    command_id=command_id,
                    type="runtime.completed",
                    actor_agent_id=agent_id,
                    work_id=work_id,
                    payload={
                        "execution_id": execution_id,
                        "workspace_path": workspace_path,
                        "workspace_branch": workspace_branch,
                        "runtime_session_id": runtime_session_id,
                        "output_summary": output_summary[:4000],
                        "total_cost_usd": total_cost_usd,
                        "total_credits": total_credits,
                        "num_turns": num_turns,
                        "started_at": started_at.isoformat(),
                        "ended_at": ended_at.isoformat(),
                        "duration_seconds": (ended_at - started_at).total_seconds(),
                    },
                )
            )
            record = ExecutionRecord(
                id=execution_id,
                run_id=run_id,
                agent_id=agent_id,
                work_id=work_id,
                workspace_path=workspace_path,
                workspace_branch=workspace_branch,
                runtime_session_id=runtime_session_id,
                output_summary=output_summary[:4000],
                total_cost_usd=total_cost_usd,
                total_credits=total_credits,
                num_turns=num_turns,
                started_at=started_at,
                ended_at=ended_at,
                duration_seconds=(ended_at - started_at).total_seconds(),
                created_seq=event.seq,
            )
            state.executions[record.id] = record
            await self.store.save_run(state, expected_version=state.version)
            return record.model_copy(deep=True)

    async def retire_agent(
        self,
        run_id: str,
        *,
        agent_id: str,
        command_id: str,
    ) -> Agent:
        async with self._lock(run_id):
            existing = await self.store.get_event_by_command(run_id, command_id)
            if existing is not None:
                state = await self.store.get_run(run_id)
                agent = state.agents.get(agent_id)
                if agent is None:
                    raise TransitionError("agent_not_found")
                return agent

            state = await self.store.get_run(run_id)
            agent = state.agents.get(agent_id)
            if agent is None:
                raise TransitionError("agent_not_found")
            if agent.status == AgentStatus.RETIRED:
                return agent.model_copy(deep=True)
            unresolved = [
                work_id
                for work_id in agent.assigned_work_ids
                if work_id in state.work_items and state.work_items[work_id].status not in _TERMINAL_WORK
            ]
            if unresolved:
                raise TransitionError("unresolved_work_assigned")

            event = await self.store.append_event(
                BarnEvent(
                    run_id=run_id,
                    command_id=command_id,
                    type="agent.retired",
                    actor_agent_id=agent_id,
                    payload={"agent_id": agent_id},
                )
            )
            agent.status = AgentStatus.RETIRED
            agent.retired_seq = event.seq
            await self.store.save_run(state, expected_version=state.version)
            return agent.model_copy(deep=True)

    async def _record_specialist_rejection(
        self,
        state: RunState,
        *,
        command_id: str,
        requester_id: str,
        work_id: str,
        capability: str,
        reason: str,
    ) -> SpecialistDecision:
        decision = SpecialistDecision(
            outcome=SpecialistOutcome.REJECTED,
            reason=reason,
            work_id=work_id,
            capability=capability,
        )
        await self.store.append_event(
            BarnEvent(
                run_id=state.id,
                command_id=command_id,
                type="specialist.rejected",
                actor_agent_id=requester_id,
                work_id=work_id,
                payload={"decision": decision.model_dump(mode="json")},
            )
        )
        return decision

    async def _commit_decision_event(
        self,
        state: RunState,
        *,
        command_id: str,
        requester_id: str,
        work_id: str,
        event_type: str,
        decision: SpecialistDecision,
    ) -> None:
        await self.store.append_event(
            BarnEvent(
                run_id=state.id,
                command_id=command_id,
                type=event_type,
                actor_agent_id=requester_id,
                work_id=work_id,
                payload={"decision": decision.model_dump(mode="json")},
            )
        )
        await self.store.save_run(state, expected_version=state.version)
