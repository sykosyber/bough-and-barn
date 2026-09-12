from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from .domain import Agent
from .runtime import AgentResult, ContextPack


class QoderDependencyError(RuntimeError):
    pass


class QoderExecutionError(RuntimeError):
    pass


class QoderAgentRuntime:
    """Qoder worker adapter; Barn, not Qoder, owns organization topology."""

    def __init__(
        self,
        *,
        cwd: str,
        model: str | None = None,
        max_turns: int = 8,
        permission_mode: str = "acceptEdits",
        mcp_server_factory: Callable[[str, Agent, ContextPack], Any] | None = None,
        auth_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.cwd = str(Path(cwd))
        self.model = model
        self.max_turns = max_turns
        self.permission_mode = permission_mode
        self.mcp_server_factory = mcp_server_factory
        self.auth_factory = auth_factory
        self._started_sessions: set[str] = set()

    @staticmethod
    def session_id_for(run_id: str, agent_id: str) -> str:
        return str(uuid5(NAMESPACE_URL, f"barn:{run_id}:{agent_id}"))

    async def run(self, agent: Agent, context: ContextPack) -> AgentResult:
        try:
            from qoder_agent_sdk import QoderAgentOptions, ResultMessage, qodercli_auth, query
        except ImportError as exc:  # pragma: no cover - package absent in CI/container
            raise QoderDependencyError(
                "qoder-agent-sdk is required to execute QoderAgentRuntime"
            ) from exc

        session_id = self.session_id_for(context.run_id, agent.id)
        max_turns = int(context.budget.get("max_turns", self.max_turns))
        visible_tools = ["Read", "Glob", "Grep", "Bash", "Edit", "Write"]
        auth = self.auth_factory() if self.auth_factory is not None else qodercli_auth()
        options_kwargs: dict[str, Any] = {
            "auth": auth,
            "cwd": context.workspace_path or self.cwd,
            "system_prompt": self._system_prompt(agent),
            "max_turns": max_turns,
            "permission_mode": self.permission_mode,
            "tools": visible_tools.copy(),
            "allowed_tools": visible_tools.copy(),
        }
        if self.model is not None:
            options_kwargs["model"] = self.model

        if session_id in self._started_sessions:
            options_kwargs["resume"] = session_id
        else:
            options_kwargs["session_id"] = session_id

        if self.mcp_server_factory is not None:
            server = self.mcp_server_factory(session_id, agent, context)
            options_kwargs["mcp_servers"] = {"barn": server}
            barn_tools = [
                "mcp__barn__request_specialist",
                "mcp__barn__propose_work",
                "mcp__barn__submit_artifact",
                "mcp__barn__get_context",
            ]
            options_kwargs["tools"] += barn_tools
            options_kwargs["allowed_tools"] += barn_tools

        options = QoderAgentOptions(**options_kwargs)
        final: Any | None = None
        async for message in query(prompt=self._prompt(context), options=options):
            if isinstance(message, ResultMessage):
                final = message

        if final is None:
            raise QoderExecutionError("Qoder stream ended without ResultMessage")
        self._started_sessions.add(session_id)

        if getattr(final, "is_error", False):
            errors = getattr(final, "errors", None)
            raise QoderExecutionError(f"Qoder execution failed: {errors or 'unknown error'}")

        return AgentResult(
            output=str(getattr(final, "result", "") or ""),
            session_id=str(getattr(final, "session_id", session_id) or session_id),
            total_cost_usd=_float_or_none(getattr(final, "total_cost_usd", None)),
            total_credits=_float_or_none(getattr(final, "total_credits", None)),
            num_turns=_int_or_none(getattr(final, "num_turns", None)),
            metadata={"provider": "qoder"},
        )

    @staticmethod
    def _system_prompt(agent: Agent) -> str:
        capabilities = ", ".join(sorted(agent.capabilities)) or "generalist"
        return (
            "You are a worker inside Barn, an artifact-conditioned organization runtime. "
            f"Your role is {agent.role}. Your declared capabilities are: {capabilities}. "
            "Do not invent, simulate, or claim that new agents exist in prose. "
            "Organization changes are valid only when committed through Barn MCP tools. "
            "Work from the supplied ContextPack, preserve explicit constraints, and produce "
            "reviewable artifacts or evidence rather than declaring success without proof."
        )

    @staticmethod
    def _prompt(context: ContextPack) -> str:
        payload = {
            "run_id": context.run_id,
            "target_work": context.target_work.model_dump(mode="json"),
            "relevant_work": [item.model_dump(mode="json") for item in context.work_items],
            "relevant_artifacts": [item.model_dump(mode="json") for item in context.artifacts],
            "budget": context.budget,
        }
        return "Execute the target Barn work item. ContextPack:\n" + json.dumps(
            payload, sort_keys=True, indent=2
        )


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
