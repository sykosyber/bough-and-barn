from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .engine import BarnEngine, TransitionError


class QoderToolDependencyError(RuntimeError):
    pass


@dataclass
class BarnToolService:
    """Barn-owned capability surface bound to one logical agent identity."""

    engine: BarnEngine
    run_id: str
    agent_id: str
    target_work_id: str
    readable_work_ids: set[str] = field(default_factory=set)
    owned_work_ids: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        self.readable_work_ids = set(self.readable_work_ids)
        self.owned_work_ids = set(self.owned_work_ids)
        self.readable_work_ids.add(self.target_work_id)
        self.owned_work_ids.add(self.target_work_id)

    def _require_owned_work(self, work_id: str) -> None:
        if work_id not in self.owned_work_ids:
            raise TransitionError("tool_work_out_of_scope")

    def _require_readable_work(self, work_id: str) -> None:
        if work_id not in self.readable_work_ids and work_id not in self.owned_work_ids:
            raise TransitionError("tool_work_out_of_scope")

    async def propose_work(
        self,
        *,
        title: str,
        description: str,
        required_capabilities: list[str],
        parent_work_id: str | None,
        dependency_ids: list[str],
        requires_verification: bool,
        priority: int,
        command_id: str,
    ) -> dict[str, Any]:
        if parent_work_id is not None:
            self._require_owned_work(parent_work_id)
        for dependency_id in dependency_ids:
            self._require_readable_work(dependency_id)
        work = await self.engine.add_work(
            self.run_id,
            actor_agent_id=self.agent_id,
            title=title,
            description=description,
            required_capabilities=set(required_capabilities),
            parent_work_id=parent_work_id,
            dependency_ids=set(dependency_ids),
            requires_verification=requires_verification,
            priority=priority,
            command_id=command_id,
        )
        self.owned_work_ids.add(work.id)
        self.readable_work_ids.add(work.id)
        return {"work": work.model_dump(mode="json")}

    async def request_specialist(
        self,
        *,
        work_id: str,
        capability: str,
        role: str,
        reason: str,
        command_id: str,
    ) -> dict[str, Any]:
        self._require_owned_work(work_id)
        decision = await self.engine.request_specialist(
            self.run_id,
            requesting_agent_id=self.agent_id,
            work_id=work_id,
            capability=capability,
            role=role,
            reason=reason,
            command_id=command_id,
        )
        return {"decision": decision.model_dump(mode="json")}

    async def submit_artifact(
        self,
        *,
        work_id: str,
        kind: str,
        uri: str,
        content_hash: str,
        command_id: str,
    ) -> dict[str, Any]:
        self._require_owned_work(work_id)
        artifact = await self.engine.submit_artifact(
            self.run_id,
            agent_id=self.agent_id,
            work_id=work_id,
            kind=kind,
            uri=uri,
            content_hash=content_hash,
            command_id=command_id,
        )
        return {"artifact": artifact.model_dump(mode="json")}

    async def get_context(self) -> dict[str, Any]:
        state = await self.engine.store.get_run(self.run_id)
        agent = state.agents.get(self.agent_id)
        target = state.work_items.get(self.target_work_id)
        if agent is None:
            raise TransitionError("tool_agent_unavailable")
        if target is None:
            raise TransitionError("tool_target_work_unavailable")

        visible_ids = self.readable_work_ids | self.owned_work_ids
        work_items = sorted(
            (item for item in state.work_items.values() if item.id in visible_ids),
            key=lambda item: (item.created_seq, item.id),
        )
        artifacts = sorted(
            (item for item in state.artifacts.values() if item.work_id in visible_ids),
            key=lambda item: (item.created_seq, item.id),
        )
        return {
            "run_id": self.run_id,
            "agent": agent.model_dump(mode="json"),
            "target_work": target.model_dump(mode="json"),
            "work_items": [item.model_dump(mode="json") for item in work_items],
            "artifacts": [item.model_dump(mode="json") for item in artifacts],
        }


def create_barn_mcp_server(service: BarnToolService) -> Any:
    """Create a fresh in-process Qoder MCP server for one Barn agent.

    The Qoder SDK documents in-process servers as query-scoped transports, so a
    fresh server config is created for each runtime invocation. Durable state
    remains in Barn's store, outside the MCP handler closure.
    """

    try:
        from qoder_agent_sdk import create_sdk_mcp_server, tool
    except ImportError as exc:  # pragma: no cover - optional integration
        raise QoderToolDependencyError(
            "qoder-agent-sdk is required to construct Barn MCP tools"
        ) from exc

    work_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "description": {"type": "string"},
            "required_capabilities": {"type": "array", "items": {"type": "string"}},
            "parent_work_id": {"type": ["string", "null"]},
            "dependency_ids": {"type": "array", "items": {"type": "string"}},
            "requires_verification": {"type": "boolean"},
            "priority": {"type": "integer"},
            "command_id": {"type": "string", "minLength": 1},
        },
        "required": [
            "title",
            "description",
            "required_capabilities",
            "parent_work_id",
            "dependency_ids",
            "requires_verification",
            "priority",
            "command_id",
        ],
        "additionalProperties": False,
    }

    specialist_schema = {
        "type": "object",
        "properties": {
            "work_id": {"type": "string", "minLength": 1},
            "capability": {"type": "string", "minLength": 1},
            "role": {"type": "string", "minLength": 1},
            "reason": {"type": "string", "minLength": 1},
            "command_id": {"type": "string", "minLength": 1},
        },
        "required": ["work_id", "capability", "role", "reason", "command_id"],
        "additionalProperties": False,
    }

    artifact_schema = {
        "type": "object",
        "properties": {
            "work_id": {"type": "string", "minLength": 1},
            "kind": {"type": "string", "minLength": 1},
            "uri": {"type": "string", "minLength": 1},
            "content_hash": {"type": "string", "minLength": 1},
            "command_id": {"type": "string", "minLength": 1},
        },
        "required": ["work_id", "kind", "uri", "content_hash", "command_id"],
        "additionalProperties": False,
    }

    empty_schema = {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    }

    @tool(
        "propose_work",
        "Create one explicit Barn work obligation. Use when the current artifact reveals work that must exist durably before execution or specialization can proceed.",
        work_schema,
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    )
    async def propose_work(args: dict[str, Any]) -> dict[str, Any]:
        return await _tool_result(service.propose_work(**args))

    @tool(
        "request_specialist",
        "Request one specialist for an existing work item and required capability. Barn may spawn, reuse, or reject the request; this is the only valid way for this worker to change crew topology.",
        specialist_schema,
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    )
    async def request_specialist(args: dict[str, Any]) -> dict[str, Any]:
        return await _tool_result(service.request_specialist(**args))

    @tool(
        "submit_artifact",
        "Attach a durable artifact and content hash to the assigned Barn work item. Use only after producing a concrete reviewable output.",
        artifact_schema,
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
    )
    async def submit_artifact(args: dict[str, Any]) -> dict[str, Any]:
        return await _tool_result(service.submit_artifact(**args))

    @tool(
        "get_context",
        "Read only the Barn work and artifacts granted to this worker's current branch. Sibling branches and global run state are intentionally hidden.",
        empty_schema,
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )
    async def get_context(args: dict[str, Any]) -> dict[str, Any]:
        del args
        return await _tool_result(service.get_context())

    return create_sdk_mcp_server(
        "barn",
        version="0.1.0",
        tools=[propose_work, request_specialist, submit_artifact, get_context],
    )


def make_barn_mcp_server_factory(engine: BarnEngine):
    """Bind Qoder MCP scope to the exact ContextPack dispatched by Barn.

    The factory deliberately derives readable work from the ContextPack and grants
    mutation ownership only for the target work item. This prevents callers from
    accidentally constructing a worker service with global run access.
    """

    def factory(session_id: str, agent: Any, context: Any) -> Any:
        del session_id
        readable = {item.id for item in context.work_items}
        service = BarnToolService(
            engine=engine,
            run_id=context.run_id,
            agent_id=agent.id,
            target_work_id=context.target_work.id,
            readable_work_ids=readable,
            owned_work_ids={context.target_work.id},
        )
        return create_barn_mcp_server(service)

    return factory


async def _tool_result(awaitable: Any) -> dict[str, Any]:
    try:
        payload = await awaitable
    except TransitionError as exc:
        return {
            "is_error": True,
            "content": [{"type": "text", "text": json.dumps({"error": str(exc)})}],
        }
    return {
        "content": [{"type": "text", "text": json.dumps(payload, sort_keys=True)}],
    }
