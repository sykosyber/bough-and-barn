from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
from typing import Any

from .domain import AgentStatus, ExecutionRecord, WorkStatus
from .engine import BarnEngine, TransitionError
from .runtime import AgentRuntime, ContextPack, build_context_pack
from .workspace import GitWorkspaceManager


class BarnOrchestrator:
    """Host-side dispatcher connecting committed Barn work to isolated workers."""

    def __init__(
        self,
        *,
        engine: BarnEngine,
        workspace_manager: GitWorkspaceManager,
        runtime: AgentRuntime,
    ) -> None:
        self.engine = engine
        self.workspace_manager = workspace_manager
        self.runtime = runtime

    async def execute_work(
        self,
        *,
        run_id: str,
        agent_id: str,
        work_id: str,
        command_id: str,
        budget: dict[str, Any] | None = None,
        base_ref: str = "HEAD",
    ) -> ExecutionRecord:
        state = await self.engine.store.get_run(run_id)
        agent = state.agents.get(agent_id)
        work = state.work_items.get(work_id)
        if agent is None or agent.status == AgentStatus.RETIRED:
            raise TransitionError("agent_unavailable")
        if work is None:
            raise TransitionError("work_not_found")
        if work.status in {WorkStatus.RESOLVED, WorkStatus.CANCELLED}:
            raise TransitionError("work_terminal")
        if any(
            state.work_items.get(dependency_id) is None
            or state.work_items[dependency_id].status != WorkStatus.RESOLVED
            for dependency_id in work.dependency_ids
        ):
            raise TransitionError("work_dependencies_unresolved")
        if work.assigned_agent_id != agent_id:
            raise TransitionError("work_not_assigned_to_agent")

        workspace = self.workspace_manager.prepare(
            run_id=run_id,
            agent_id=agent_id,
            base_ref=base_ref,
        )
        context = await build_context_pack(
            self.engine.store,
            run_id=run_id,
            agent_id=agent_id,
            work_id=work_id,
            budget=budget or {},
        )
        context = context.model_copy(
            update={
                "workspace_path": str(workspace.path),
                "workspace_branch": workspace.branch,
            }
        )
        context = _materialize_context_artifacts(context, workspace.path)

        started_at = datetime.now(timezone.utc)
        result = await self.runtime.run(context.agent, context)
        ended_at = datetime.now(timezone.utc)

        return await self.engine.record_execution(
            run_id,
            agent_id=agent_id,
            work_id=work_id,
            workspace_path=str(workspace.path),
            workspace_branch=workspace.branch,
            output_summary=result.output,
            started_at=started_at,
            ended_at=ended_at,
            runtime_session_id=result.session_id,
            total_cost_usd=result.total_cost_usd,
            total_credits=result.total_credits,
            num_turns=result.num_turns,
            command_id=command_id,
        )


def _materialize_context_artifacts(context: ContextPack, workspace: Path) -> ContextPack:
    """Copy bounded local artifacts into the receiving worker's own worktree.

    The committed artifact hash is verified before any bytes enter the worker
    workspace. Non-local artifact URIs remain references; Barn does not fetch
    network content implicitly.
    """

    materialized = []
    root = workspace / ".barn" / "context" / "artifacts"
    for artifact in context.artifacts:
        source = _local_artifact_path(artifact.uri)
        if source is None:
            materialized.append(artifact)
            continue
        payload = source.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if digest != artifact.content_hash:
            raise TransitionError("artifact_integrity_failed")
        destination_dir = root / artifact.id
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / (source.name or "artifact.bin")
        destination.write_bytes(payload)
        materialized.append(artifact.model_copy(update={"uri": f"file://{destination}"}))
    return context.model_copy(update={"artifacts": materialized})


def _local_artifact_path(uri: str) -> Path | None:
    if uri.startswith("file://"):
        return Path(uri[7:]).expanduser().resolve()
    if "://" in uri:
        return None
    return Path(uri).expanduser().resolve()
