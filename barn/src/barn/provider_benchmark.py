from __future__ import annotations

import hashlib
import importlib.util
import os
from collections.abc import Callable, Mapping
from pathlib import Path

from pydantic import BaseModel, Field

from .audit import audit_run
from .benchmark import ComparisonReport, PolicyResult, _init_fixture_repo
from .engine import BarnEngine
from .metrics import summarize_run
from .orchestrator import BarnOrchestrator
from .runtime import AgentRuntime
from .store import InMemoryGraphStore
from .workspace import GitWorkspaceManager

RuntimeFactory = Callable[[BarnEngine, Path], AgentRuntime]


class QoderBenchmarkPrerequisites(BaseModel):
    ready: bool
    missing: list[str] = Field(default_factory=list)
    auth_mode: str | None = None


def check_qoder_benchmark_prerequisites(
    *,
    environ: Mapping[str, str] | None = None,
    module_available: Callable[[str], bool] | None = None,
) -> QoderBenchmarkPrerequisites:
    env = os.environ if environ is None else environ
    module_available = module_available or (lambda name: importlib.util.find_spec(name) is not None)
    if not module_available("qoder_agent_sdk"):
        return QoderBenchmarkPrerequisites(
            ready=False,
            missing=["python_module:qoder_agent_sdk"],
            auth_mode=None,
        )
    auth_mode = "pat" if env.get("QODER_PERSONAL_ACCESS_TOKEN") else "qodercli"
    return QoderBenchmarkPrerequisites(ready=True, auth_mode=auth_mode)


class _TurnBudget:
    def __init__(self, limit: int) -> None:
        if limit < 1:
            raise ValueError("max_total_turns must be >= 1")
        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int:
        return self.limit - self.used

    def consume(self, turns: int | None) -> None:
        if turns is None:
            raise RuntimeError("runtime_turn_count_missing")
        if turns < 0 or self.used + turns > self.limit:
            raise RuntimeError("turn_budget_exhausted")
        self.used += turns


async def run_model_comparison(
    base_dir: str | Path,
    *,
    runtime_factory: RuntimeFactory,
    max_total_turns: int = 6,
    evidence_grade: str = "provider_backed_if_runtime_is_real",
) -> ComparisonReport:
    """Run the three-policy benchmark with a runtime that submits its own artifacts.

    Unlike the synthetic smoke benchmark, the host does not manufacture artifact
    records after a worker returns. A runtime must create the expected file and
    submit it through Barn during the invocation. The host only verifies bytes,
    hash, scope, and then resolves the completed work item.
    """

    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    results = [
        await _single(base / "single", runtime_factory, max_total_turns),
        await _fixed(base / "fixed-team", runtime_factory, max_total_turns),
        await _barn(base / "barn", runtime_factory, max_total_turns),
    ]
    return ComparisonReport(
        task_name="two_stage_provider_artifact_benchmark",
        evidence_grade=evidence_grade,
        max_total_turns=max_total_turns,
        results=results,
        interpretation=(
            "All policies share the same total model-turn ceiling and acceptance bytes. "
            "Interpret model-performance claims only when runtime_factory is an actual pinned provider runtime."
        ),
    )


async def _single(repo: Path, runtime_factory: RuntimeFactory, turn_limit: int) -> PolicyResult:
    _init_fixture_repo(repo)
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal=(
            "Implement the benchmark contract without creating specialists. Create solution.txt containing exactly "
            "BARN_MODEL_BENCH_OK followed by a newline, compute its SHA-256, and submit it as a Barn artifact for "
            "this work before returning."
        ),
        max_active_agents=3,
        chief_capabilities={"architecture", "python"},
        command_id="single-run",
        run_id="provider-single",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    budget = _TurnBudget(turn_limit)
    orchestrator = BarnOrchestrator(
        engine=engine,
        workspace_manager=GitWorkspaceManager(repo),
        runtime=runtime_factory(engine, repo),
    )
    record = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=chief.id,
        work_id=root.id,
        command_id="single-execute",
        budget={"max_turns": budget.remaining},
    )
    budget.consume(record.num_turns)
    await _accept_artifact(engine, run.id, record.workspace_path, root.id, chief.id, "solution.txt", b"BARN_MODEL_BENCH_OK\n")
    return await _policy_result(engine, run.id, "single", turn_limit, record.workspace_path)


async def _fixed(repo: Path, runtime_factory: RuntimeFactory, turn_limit: int) -> PolicyResult:
    _init_fixture_repo(repo)
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Implement the two-stage benchmark contract using the fixed pre-staffed team.",
        max_active_agents=4,
        chief_capabilities={"generalist"},
        command_id="fixed-run",
        run_id="provider-fixed",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    architecture = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Architecture stage",
        description=(
            "Create architecture.md with a concise implementation plan, compute SHA-256, and submit it as a Barn "
            "artifact for this work before returning."
        ),
        required_capabilities={"architecture"},
        parent_work_id=root.id,
        command_id="fixed-architecture-work",
    )
    implementation = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implementation stage",
        description=(
            "Use the materialized dependency artifact. Create solution.txt containing exactly BARN_MODEL_BENCH_OK "
            "followed by a newline, compute SHA-256, and submit it as a Barn artifact for this work before returning."
        ),
        required_capabilities={"python"},
        parent_work_id=root.id,
        dependency_ids={architecture.id},
        command_id="fixed-implementation-work",
    )
    architect = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=architecture.id,
        capability="architecture",
        role="Architect",
        reason="Fixed team pre-staffs architecture",
        command_id="fixed-architect",
    )
    builder = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=implementation.id,
        capability="python",
        role="Builder",
        reason="Fixed team pre-staffs implementation",
        command_id="fixed-builder",
    )
    budget = _TurnBudget(turn_limit)
    orchestrator = BarnOrchestrator(
        engine=engine,
        workspace_manager=GitWorkspaceManager(repo),
        runtime=runtime_factory(engine, repo),
    )
    arch_record = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=str(architect.agent_id),
        work_id=architecture.id,
        command_id="fixed-architecture-execute",
        budget={"max_turns": budget.remaining},
    )
    budget.consume(arch_record.num_turns)
    await _accept_artifact(engine, run.id, arch_record.workspace_path, architecture.id, str(architect.agent_id), "architecture.md")
    impl_record = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=str(builder.agent_id),
        work_id=implementation.id,
        command_id="fixed-implementation-execute",
        budget={"max_turns": budget.remaining},
    )
    budget.consume(impl_record.num_turns)
    await _accept_artifact(
        engine,
        run.id,
        impl_record.workspace_path,
        implementation.id,
        str(builder.agent_id),
        "solution.txt",
        b"BARN_MODEL_BENCH_OK\n",
    )
    await engine.retire_agent(run.id, agent_id=str(architect.agent_id), command_id="fixed-retire-architect")
    await engine.retire_agent(run.id, agent_id=str(builder.agent_id), command_id="fixed-retire-builder")
    return await _policy_result(engine, run.id, "fixed_team", turn_limit, impl_record.workspace_path)


async def _barn(repo: Path, runtime_factory: RuntimeFactory, turn_limit: int) -> PolicyResult:
    _init_fixture_repo(repo)
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Implement the two-stage benchmark contract using artifact-conditioned specialization.",
        max_active_agents=4,
        chief_capabilities={"architecture"},
        command_id="barn-run",
        run_id="provider-barn",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    architecture = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Architecture stage",
        description=(
            "Create architecture.md with a concise implementation plan, compute SHA-256, and submit it as a Barn "
            "artifact for this work before returning."
        ),
        required_capabilities={"architecture"},
        parent_work_id=root.id,
        command_id="barn-architecture-work",
    )
    await engine.assign_work(
        run.id,
        agent_id=chief.id,
        work_id=architecture.id,
        command_id="barn-architecture-assign",
    )
    budget = _TurnBudget(turn_limit)
    orchestrator = BarnOrchestrator(
        engine=engine,
        workspace_manager=GitWorkspaceManager(repo),
        runtime=runtime_factory(engine, repo),
    )
    arch_record = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=chief.id,
        work_id=architecture.id,
        command_id="barn-architecture-execute",
        budget={"max_turns": budget.remaining},
    )
    budget.consume(arch_record.num_turns)
    await _accept_artifact(engine, run.id, arch_record.workspace_path, architecture.id, chief.id, "architecture.md")

    implementation = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implementation stage",
        description=(
            "Use the materialized dependency artifact. Create solution.txt containing exactly BARN_MODEL_BENCH_OK "
            "followed by a newline, compute SHA-256, and submit it as a Barn artifact for this work before returning."
        ),
        required_capabilities={"python"},
        parent_work_id=root.id,
        dependency_ids={architecture.id},
        command_id="barn-implementation-work",
    )
    builder = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=implementation.id,
        capability="python",
        role="Builder",
        reason="Resolved architecture exposed an implementation capability gap",
        command_id="barn-builder",
    )
    impl_record = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=str(builder.agent_id),
        work_id=implementation.id,
        command_id="barn-implementation-execute",
        budget={"max_turns": budget.remaining},
    )
    budget.consume(impl_record.num_turns)
    await _accept_artifact(
        engine,
        run.id,
        impl_record.workspace_path,
        implementation.id,
        str(builder.agent_id),
        "solution.txt",
        b"BARN_MODEL_BENCH_OK\n",
    )
    await engine.retire_agent(run.id, agent_id=str(builder.agent_id), command_id="barn-retire-builder")
    return await _policy_result(engine, run.id, "barn", turn_limit, impl_record.workspace_path)


async def _accept_artifact(
    engine: BarnEngine,
    run_id: str,
    workspace_path: str,
    work_id: str,
    agent_id: str,
    expected_filename: str,
    expected_bytes: bytes | None = None,
) -> None:
    state = await engine.store.get_run(run_id)
    artifacts = [
        artifact
        for artifact in state.artifacts.values()
        if artifact.work_id == work_id and artifact.producer_agent_id == agent_id
    ]
    if len(artifacts) != 1:
        raise RuntimeError(f"expected_one_runtime_submitted_artifact:{work_id}:{len(artifacts)}")
    artifact = artifacts[0]
    workspace = Path(workspace_path).resolve()
    path = _artifact_path(artifact.uri, workspace).resolve()
    if not path.is_relative_to(workspace):
        raise RuntimeError("artifact_outside_worker_workspace")
    if path.name != expected_filename or not path.is_file():
        raise RuntimeError("expected_artifact_file_missing")
    payload = path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != artifact.content_hash:
        raise RuntimeError("artifact_hash_mismatch")
    if expected_bytes is not None and payload != expected_bytes:
        raise RuntimeError("artifact_acceptance_bytes_mismatch")
    if expected_bytes is None and not payload:
        raise RuntimeError("artifact_empty")
    await engine.resolve_work(
        run_id,
        actor_agent_id=agent_id,
        work_id=work_id,
        command_id=f"accept-{work_id}",
    )


async def _policy_result(
    engine: BarnEngine,
    run_id: str,
    policy: str,
    turn_budget: int,
    final_workspace: str,
) -> PolicyResult:
    state = await engine.store.get_run(run_id)
    events = await engine.store.list_events(run_id)
    metrics = summarize_run(state, events)
    audit = await audit_run(engine.store, run_id)
    solution = Path(final_workspace) / "solution.txt"
    passed = solution.is_file() and solution.read_bytes() == b"BARN_MODEL_BENCH_OK\n"
    return PolicyResult(
        policy=policy,
        passed=passed,
        turn_budget=turn_budget,
        turns_used=metrics.runtime_turns_total,
        credits_used=metrics.runtime_credits_total,
        runtime_executions=metrics.runtime_executions,
        agent_total=metrics.agent_total,
        specialists_spawned=metrics.specialist_spawned,
        audit_matches=audit.matches,
    )


def _artifact_path(uri: str, workspace: Path) -> Path:
    if uri.startswith("file://"):
        candidate = Path(uri[7:])
    elif "://" in uri:
        raise RuntimeError("benchmark_requires_local_artifact")
    else:
        candidate = Path(uri)
    return candidate if candidate.is_absolute() else workspace / candidate
