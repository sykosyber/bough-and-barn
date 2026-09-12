from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .audit import audit_run
from .causal import why_agent_exists
from .demo import bootstrap_demo, complete_demo
from .engine import BarnEngine, TransitionError
from .metrics import summarize_run
from .store import GraphStore, InMemoryGraphStore, RunNotFoundError


def _command_id() -> str:
    return f"cmd_{uuid4().hex}"


class CreateRunRequest(BaseModel):
    goal: str = Field(min_length=1)
    max_active_agents: int = Field(default=6, ge=1)
    chief_capabilities: set[str] = Field(default_factory=lambda: {"generalist"})
    command_id: str = Field(default_factory=_command_id)


class AddWorkRequest(BaseModel):
    actor_agent_id: str
    title: str = Field(min_length=1)
    description: str = ""
    required_capabilities: set[str] = Field(default_factory=set)
    parent_work_id: str | None = None
    dependency_ids: set[str] = Field(default_factory=set)
    requires_verification: bool = False
    priority: int = 0
    command_id: str = Field(default_factory=_command_id)


class AssignRequest(BaseModel):
    agent_id: str
    command_id: str = Field(default_factory=_command_id)


class SpecialistRequest(BaseModel):
    requesting_agent_id: str
    work_id: str
    capability: str = Field(min_length=1)
    role: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    command_id: str = Field(default_factory=_command_id)


class ArtifactRequest(BaseModel):
    agent_id: str
    work_id: str
    kind: str
    uri: str
    content_hash: str
    command_id: str = Field(default_factory=_command_id)


class VerificationRequest(BaseModel):
    verifier_agent_id: str
    artifact_id: str
    passed: bool
    evidence: str
    command_id: str = Field(default_factory=_command_id)


class ResolveRequest(BaseModel):
    actor_agent_id: str
    command_id: str = Field(default_factory=_command_id)


class RetireRequest(BaseModel):
    command_id: str = Field(default_factory=_command_id)


def create_app(store: GraphStore | None = None) -> FastAPI:
    app = FastAPI(title="Barn", version="0.1.0")
    static_dir = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    engine = BarnEngine(store or InMemoryGraphStore())
    app.state.engine = engine

    @app.exception_handler(TransitionError)
    async def transition_error_handler(_request, exc: TransitionError):
        return _json_error(status.HTTP_409_CONFLICT, str(exc))

    @app.exception_handler(RunNotFoundError)
    async def run_not_found_handler(_request, exc: RunNotFoundError):
        return _json_error(status.HTTP_404_NOT_FOUND, f"run_not_found:{exc.args[0]}")

    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/runs", status_code=status.HTTP_201_CREATED)
    async def create_run(request: CreateRunRequest) -> dict[str, Any]:
        run = await engine.create_run(
            goal=request.goal,
            max_active_agents=request.max_active_agents,
            chief_capabilities=request.chief_capabilities,
            command_id=request.command_id,
        )
        return run.model_dump(mode="json")

    @app.get("/runs/{run_id}/snapshot")
    async def snapshot(run_id: str) -> dict[str, Any]:
        state = await engine.store.get_run(run_id)
        events = await engine.store.list_events(run_id)
        return {
            "state": state.model_dump(mode="json"),
            "events": [event.model_dump(mode="json") for event in events],
        }

    @app.get("/runs/{run_id}/metrics")
    async def metrics(run_id: str) -> dict[str, Any]:
        state = await engine.store.get_run(run_id)
        events = await engine.store.list_events(run_id)
        return summarize_run(state, events).model_dump(mode="json")

    @app.get("/runs/{run_id}/audit")
    async def audit(run_id: str) -> dict[str, Any]:
        report = await audit_run(engine.store, run_id)
        return report.model_dump(mode="json")

    @app.post("/runs/{run_id}/work", status_code=status.HTTP_201_CREATED)
    async def add_work(run_id: str, request: AddWorkRequest) -> dict[str, Any]:
        work = await engine.add_work(
            run_id,
            actor_agent_id=request.actor_agent_id,
            title=request.title,
            description=request.description,
            required_capabilities=request.required_capabilities,
            parent_work_id=request.parent_work_id,
            dependency_ids=request.dependency_ids,
            requires_verification=request.requires_verification,
            priority=request.priority,
            command_id=request.command_id,
        )
        return work.model_dump(mode="json")

    @app.post("/runs/{run_id}/work/{work_id}/assign")
    async def assign_work(run_id: str, work_id: str, request: AssignRequest) -> dict[str, Any]:
        work = await engine.assign_work(
            run_id,
            agent_id=request.agent_id,
            work_id=work_id,
            command_id=request.command_id,
        )
        return work.model_dump(mode="json")

    @app.post("/runs/{run_id}/specialists/request")
    async def request_specialist(run_id: str, request: SpecialistRequest) -> dict[str, Any]:
        decision = await engine.request_specialist(
            run_id,
            requesting_agent_id=request.requesting_agent_id,
            work_id=request.work_id,
            capability=request.capability,
            role=request.role,
            reason=request.reason,
            command_id=request.command_id,
        )
        return decision.model_dump(mode="json")

    @app.post("/runs/{run_id}/artifacts", status_code=status.HTTP_201_CREATED)
    async def submit_artifact(run_id: str, request: ArtifactRequest) -> dict[str, Any]:
        artifact = await engine.submit_artifact(run_id, **request.model_dump())
        return artifact.model_dump(mode="json")

    @app.post("/runs/{run_id}/verifications", status_code=status.HTTP_201_CREATED)
    async def record_verification(run_id: str, request: VerificationRequest) -> dict[str, Any]:
        verification = await engine.record_verification(run_id, **request.model_dump())
        return verification.model_dump(mode="json")

    @app.post("/runs/{run_id}/work/{work_id}/resolve")
    async def resolve_work(run_id: str, work_id: str, request: ResolveRequest) -> dict[str, Any]:
        work = await engine.resolve_work(
            run_id,
            actor_agent_id=request.actor_agent_id,
            work_id=work_id,
            command_id=request.command_id,
        )
        return work.model_dump(mode="json")

    @app.post("/runs/{run_id}/agents/{agent_id}/retire")
    async def retire_agent(run_id: str, agent_id: str, request: RetireRequest) -> dict[str, Any]:
        agent = await engine.retire_agent(run_id, agent_id=agent_id, command_id=request.command_id)
        return agent.model_dump(mode="json")

    @app.get("/runs/{run_id}/agents/{agent_id}/why")
    async def why(run_id: str, agent_id: str) -> dict[str, Any]:
        try:
            explanation = await why_agent_exists(engine.store, run_id, agent_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"agent_not_found:{agent_id}") from exc
        return explanation.model_dump(mode="json")

    @app.post("/demo/bootstrap", status_code=status.HTTP_201_CREATED)
    async def demo() -> dict[str, Any]:
        return await bootstrap_demo(engine)

    @app.post("/demo/{run_id}/complete")
    async def demo_complete(run_id: str) -> dict[str, Any]:
        return await complete_demo(engine, run_id)

    return app


def _json_error(status_code: int, detail: str):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={"detail": detail})


app = create_app()
