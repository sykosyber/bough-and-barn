from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AgentStatus(StrEnum):
    ACTIVE = "active"
    IDLE = "idle"
    RETIRED = "retired"


class WorkStatus(StrEnum):
    PROPOSED = "proposed"
    READY = "ready"
    ACTIVE = "active"
    BLOCKED = "blocked"
    REVIEW = "review"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class Agent(BaseModel):
    id: str
    run_id: str
    role: str
    capabilities: set[str] = Field(default_factory=set)
    status: AgentStatus = AgentStatus.ACTIVE
    parent_agent_id: str | None = None
    spawned_because_work_id: str | None = None
    spawn_reason: str | None = None
    runtime_session_id: str | None = None
    assigned_work_ids: set[str] = Field(default_factory=set)
    created_seq: int = 0
    retired_seq: int | None = None


class WorkItem(BaseModel):
    id: str
    run_id: str
    title: str
    description: str = ""
    status: WorkStatus = WorkStatus.PROPOSED
    required_capabilities: set[str] = Field(default_factory=set)
    parent_work_id: str | None = None
    dependency_ids: set[str] = Field(default_factory=set)
    assigned_agent_id: str | None = None
    requires_verification: bool = False
    priority: int = 0
    created_seq: int = 0
    resolved_seq: int | None = None


class Artifact(BaseModel):
    id: str
    run_id: str
    work_id: str
    producer_agent_id: str
    kind: str
    uri: str
    content_hash: str
    created_seq: int = 0


class Verification(BaseModel):
    id: str
    run_id: str
    artifact_id: str
    verifier_agent_id: str
    passed: bool
    evidence: str
    created_seq: int = 0


class ExecutionRecord(BaseModel):
    id: str
    run_id: str
    agent_id: str
    work_id: str
    workspace_path: str
    workspace_branch: str
    runtime_session_id: str | None = None
    output_summary: str = ""
    total_cost_usd: float | None = None
    total_credits: float | None = None
    num_turns: int | None = None
    started_at: datetime
    ended_at: datetime
    duration_seconds: float = Field(ge=0)
    created_seq: int = 0


class BarnEvent(BaseModel):
    seq: int = 0
    run_id: str
    command_id: str
    type: str
    actor_agent_id: str | None = None
    work_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RunState(BaseModel):
    id: str
    goal: str
    max_active_agents: int = Field(default=6, ge=1)
    agents: dict[str, Agent] = Field(default_factory=dict)
    work_items: dict[str, WorkItem] = Field(default_factory=dict)
    artifacts: dict[str, Artifact] = Field(default_factory=dict)
    verifications: dict[str, Verification] = Field(default_factory=dict)
    executions: dict[str, ExecutionRecord] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    version: int = 0
