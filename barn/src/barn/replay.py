from __future__ import annotations

from datetime import datetime

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


class ReplayError(ValueError):
    pass


def replay_run(events: list[BarnEvent]) -> RunState:
    if not events:
        raise ReplayError("event_log_empty")
    run_id = events[0].run_id
    for expected_seq, event in enumerate(events, start=1):
        if event.seq != expected_seq:
            raise ReplayError("event_sequence_invalid")
        if event.run_id != run_id:
            raise ReplayError("event_run_mismatch")

    first = events[0]
    if first.type != "run.created":
        raise ReplayError("first_event_must_create_run")
    payload = first.payload
    required = {
        "goal",
        "max_active_agents",
        "chief_agent_id",
        "chief_capabilities",
        "goal_work_id",
    }
    if not required.issubset(payload):
        raise ReplayError("run_created_payload_incomplete")

    chief_id = str(payload["chief_agent_id"])
    goal_work_id = str(payload["goal_work_id"])
    chief = Agent(
        id=chief_id,
        run_id=run_id,
        role="Chief",
        capabilities=set(payload["chief_capabilities"]),
        status=AgentStatus.ACTIVE,
        assigned_work_ids={goal_work_id},
        created_seq=first.seq,
    )
    root = WorkItem(
        id=goal_work_id,
        run_id=run_id,
        title=str(payload["goal"]),
        description="Root goal",
        status=WorkStatus.ACTIVE,
        assigned_agent_id=chief_id,
        created_seq=first.seq,
    )
    state = RunState(
        id=run_id,
        goal=str(payload["goal"]),
        max_active_agents=int(payload["max_active_agents"]),
        agents={chief_id: chief},
        work_items={goal_work_id: root},
        created_at=first.created_at,
        version=0,
    )

    for event in events[1:]:
        _apply_event(state, event)
    return state


def _apply_event(state: RunState, event: BarnEvent) -> None:
    payload = event.payload
    if event.type == "work.created":
        work_id = str(payload["work_id"])
        state.work_items[work_id] = WorkItem(
            id=work_id,
            run_id=state.id,
            title=str(payload["title"]),
            description=str(payload.get("description", "")),
            status=WorkStatus(payload["status"]),
            required_capabilities=set(payload.get("required_capabilities", [])),
            parent_work_id=payload.get("parent_work_id"),
            dependency_ids=set(payload.get("dependency_ids", [])),
            requires_verification=bool(payload.get("requires_verification", False)),
            priority=int(payload.get("priority", 0)),
            created_seq=event.seq,
        )
        return

    if event.type == "work.assigned":
        agent_id = str(payload["agent_id"])
        work_id = str(payload["work_id"])
        agent = _agent(state, agent_id)
        work = _work(state, work_id)
        work.assigned_agent_id = agent_id
        work.status = WorkStatus.ACTIVE
        agent.assigned_work_ids.add(work_id)
        agent.status = AgentStatus.ACTIVE
        return

    if event.type == "specialist.spawned":
        decision = payload["decision"]
        agent_id = str(decision["agent_id"])
        work_id = str(decision["work_id"])
        capability = str(decision["capability"])
        specialist = Agent(
            id=agent_id,
            run_id=state.id,
            role=str(payload["role"]),
            capabilities={capability},
            status=AgentStatus.ACTIVE,
            parent_agent_id=event.actor_agent_id,
            spawned_because_work_id=work_id,
            spawn_reason=str(payload["reason"]),
            assigned_work_ids={work_id},
            created_seq=event.seq,
        )
        state.agents[agent_id] = specialist
        work = _work(state, work_id)
        work.assigned_agent_id = agent_id
        if work.status == WorkStatus.READY:
            work.status = WorkStatus.ACTIVE
        return

    if event.type == "specialist.reused":
        decision = payload["decision"]
        agent_id = str(decision["agent_id"])
        work_id = str(decision["work_id"])
        agent = _agent(state, agent_id)
        work = _work(state, work_id)
        agent.assigned_work_ids.add(work_id)
        agent.status = AgentStatus.ACTIVE
        work.assigned_agent_id = agent_id
        if work.status == WorkStatus.READY:
            work.status = WorkStatus.ACTIVE
        return

    if event.type == "specialist.rejected":
        return

    if event.type == "artifact.submitted":
        artifact_id = str(payload["artifact_id"])
        work_id = _event_work_id(event)
        producer = _event_actor_id(event)
        state.artifacts[artifact_id] = Artifact(
            id=artifact_id,
            run_id=state.id,
            work_id=work_id,
            producer_agent_id=producer,
            kind=str(payload["kind"]),
            uri=str(payload["uri"]),
            content_hash=str(payload["content_hash"]),
            created_seq=event.seq,
        )
        work = _work(state, work_id)
        if work.status == WorkStatus.ACTIVE:
            work.status = WorkStatus.REVIEW
        return

    if event.type == "artifact.verified":
        verification_id = str(payload["verification_id"])
        state.verifications[verification_id] = Verification(
            id=verification_id,
            run_id=state.id,
            artifact_id=str(payload["artifact_id"]),
            verifier_agent_id=_event_actor_id(event),
            passed=bool(payload["passed"]),
            evidence=str(payload["evidence"]),
            created_seq=event.seq,
        )
        return

    if event.type == "work.resolved":
        work_id = _event_work_id(event)
        work = _work(state, work_id)
        work.status = WorkStatus.RESOLVED
        work.resolved_seq = event.seq
        if work.assigned_agent_id is not None:
            agent = _agent(state, work.assigned_agent_id)
            agent.assigned_work_ids.discard(work_id)
            if not agent.assigned_work_ids:
                agent.status = AgentStatus.IDLE
        return

    if event.type == "runtime.completed":
        execution_id = str(payload["execution_id"])
        state.executions[execution_id] = ExecutionRecord(
            id=execution_id,
            run_id=state.id,
            agent_id=_event_actor_id(event),
            work_id=_event_work_id(event),
            workspace_path=str(payload["workspace_path"]),
            workspace_branch=str(payload["workspace_branch"]),
            runtime_session_id=payload.get("runtime_session_id"),
            output_summary=str(payload.get("output_summary", "")),
            total_cost_usd=_optional_float(payload.get("total_cost_usd")),
            total_credits=_optional_float(payload.get("total_credits")),
            num_turns=_optional_int(payload.get("num_turns")),
            started_at=_parse_datetime(payload["started_at"]),
            ended_at=_parse_datetime(payload["ended_at"]),
            duration_seconds=float(payload["duration_seconds"]),
            created_seq=event.seq,
        )
        return

    if event.type == "agent.retired":
        agent_id = str(payload.get("agent_id") or _event_actor_id(event))
        agent = _agent(state, agent_id)
        agent.status = AgentStatus.RETIRED
        agent.retired_seq = event.seq
        return

    raise ReplayError(f"unknown_event_type:{event.type}")


def _agent(state: RunState, agent_id: str) -> Agent:
    try:
        return state.agents[agent_id]
    except KeyError as exc:
        raise ReplayError(f"agent_missing:{agent_id}") from exc


def _work(state: RunState, work_id: str) -> WorkItem:
    try:
        return state.work_items[work_id]
    except KeyError as exc:
        raise ReplayError(f"work_missing:{work_id}") from exc


def _event_actor_id(event: BarnEvent) -> str:
    if event.actor_agent_id is None:
        raise ReplayError(f"event_actor_missing:{event.type}")
    return event.actor_agent_id


def _event_work_id(event: BarnEvent) -> str:
    if event.work_id is None:
        raise ReplayError(f"event_work_missing:{event.type}")
    return event.work_id


def _parse_datetime(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


def _optional_float(value) -> float | None:
    return None if value is None else float(value)


def _optional_int(value) -> int | None:
    return None if value is None else int(value)
