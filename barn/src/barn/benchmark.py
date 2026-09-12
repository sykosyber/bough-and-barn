from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from pydantic import BaseModel

from .audit import audit_run
from .engine import BarnEngine
from .metrics import summarize_run
from .orchestrator import BarnOrchestrator
from .runtime import AgentResult, ScriptedRuntime
from .store import InMemoryGraphStore
from .workspace import GitWorkspaceManager


class PolicyResult(BaseModel):
    policy: str
    passed: bool
    turn_budget: int
    turns_used: int
    credits_used: float
    runtime_executions: int
    agent_total: int
    specialists_spawned: int
    audit_matches: bool


class ComparisonReport(BaseModel):
    task_name: str
    evidence_grade: str
    max_total_turns: int
    results: list[PolicyResult]
    interpretation: str


class _Budget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def consume(self, turns: int) -> None:
        if self.used + turns > self.limit:
            raise RuntimeError("turn_budget_exhausted")
        self.used += turns


async def run_synthetic_comparison(base_dir: str | Path, *, max_total_turns: int = 3) -> ComparisonReport:
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    results = [
        await _run_single(base / "single", max_total_turns),
        await _run_fixed_team(base / "fixed-team", max_total_turns),
        await _run_barn(base / "barn", max_total_turns),
    ]
    by_policy = {item.policy: item for item in results}
    interpretation = interpret_synthetic_results(
        single_turns=by_policy["single"].turns_used,
        fixed_turns=by_policy["fixed_team"].turns_used,
        barn_turns=by_policy["barn"].turns_used,
        fixed_agents=by_policy["fixed_team"].agent_total,
        barn_agents=by_policy["barn"].agent_total,
    )
    return ComparisonReport(
        task_name="two_stage_implementation_smoke",
        evidence_grade="synthetic_smoke_not_model_performance",
        max_total_turns=max_total_turns,
        results=results,
        interpretation=interpretation,
    )


def interpret_synthetic_results(
    *,
    single_turns: int,
    fixed_turns: int,
    barn_turns: int,
    fixed_agents: int,
    barn_agents: int,
) -> str:
    parts: list[str] = []
    if single_turns < barn_turns:
        parts.append("On this simple scripted task, the single-agent baseline is more inference-efficient than Barn.")
    elif single_turns == barn_turns:
        parts.append("On this simple scripted task, Barn does not improve inference efficiency over the single-agent baseline.")
    else:
        parts.append("On this scripted task Barn uses fewer turns than the single-agent baseline, but the worker is synthetic.")
    if barn_agents < fixed_agents:
        parts.append("Barn uses fewer staffed agents than the fixed team by delaying specialization until the implementation capability gap appears.")
    else:
        parts.append("Barn does not reduce staffed-agent count relative to the fixed team on this fixture.")
    parts.append("This is a coordination-plumbing smoke test, not evidence that Barn improves real model performance.")
    return " ".join(parts)


async def _run_single(repo: Path, turn_budget: int) -> PolicyResult:
    _init_fixture_repo(repo)
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Implement benchmark service",
        max_active_agents=3,
        chief_capabilities={"architecture", "python"},
        command_id="single-run",
        run_id="benchmark-single",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    budget = _Budget(turn_budget)
    orchestrator = _orchestrator(engine, repo, budget)
    execution = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=chief.id,
        work_id=root.id,
        command_id="single-execute",
        budget={"max_turns": turn_budget},
    )
    await _attach_and_resolve(engine, execution, root.id, chief.id, "solution.txt", "single")
    return await _result(engine, repo, run.id, "single", turn_budget, execution.workspace_path)


async def _run_fixed_team(repo: Path, turn_budget: int) -> PolicyResult:
    _init_fixture_repo(repo)
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Implement benchmark service",
        max_active_agents=4,
        chief_capabilities={"generalist"},
        command_id="fixed-run",
        run_id="benchmark-fixed",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    architecture = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Architecture stage",
        required_capabilities={"architecture"},
        parent_work_id=root.id,
        command_id="fixed-architecture-work",
    )
    implementation = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implementation stage",
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
    budget = _Budget(turn_budget)
    orchestrator = _orchestrator(engine, repo, budget)
    arch_execution = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=str(architect.agent_id),
        work_id=architecture.id,
        command_id="fixed-architecture-execute",
        budget={"max_turns": turn_budget - budget.used},
    )
    await _attach_and_resolve(engine, arch_execution, architecture.id, str(architect.agent_id), "architecture.md", "fixed-arch")
    impl_execution = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=str(builder.agent_id),
        work_id=implementation.id,
        command_id="fixed-implementation-execute",
        budget={"max_turns": turn_budget - budget.used},
    )
    await _attach_and_resolve(engine, impl_execution, implementation.id, str(builder.agent_id), "solution.txt", "fixed-impl")
    await engine.retire_agent(run.id, agent_id=str(architect.agent_id), command_id="fixed-retire-architect")
    await engine.retire_agent(run.id, agent_id=str(builder.agent_id), command_id="fixed-retire-builder")
    return await _result(engine, repo, run.id, "fixed_team", turn_budget, impl_execution.workspace_path)


async def _run_barn(repo: Path, turn_budget: int) -> PolicyResult:
    _init_fixture_repo(repo)
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Implement benchmark service",
        max_active_agents=4,
        chief_capabilities={"architecture"},
        command_id="barn-run",
        run_id="benchmark-barn",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    architecture = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Architecture stage",
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
    budget = _Budget(turn_budget)
    orchestrator = _orchestrator(engine, repo, budget)
    arch_execution = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=chief.id,
        work_id=architecture.id,
        command_id="barn-architecture-execute",
        budget={"max_turns": turn_budget - budget.used},
    )
    await _attach_and_resolve(engine, arch_execution, architecture.id, chief.id, "architecture.md", "barn-arch")

    implementation = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implementation stage",
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
    impl_execution = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=str(builder.agent_id),
        work_id=implementation.id,
        command_id="barn-implementation-execute",
        budget={"max_turns": turn_budget - budget.used},
    )
    await _attach_and_resolve(engine, impl_execution, implementation.id, str(builder.agent_id), "solution.txt", "barn-impl")
    await engine.retire_agent(run.id, agent_id=str(builder.agent_id), command_id="barn-retire-builder")
    return await _result(engine, repo, run.id, "barn", turn_budget, impl_execution.workspace_path)


def _orchestrator(engine: BarnEngine, repo: Path, budget: _Budget) -> BarnOrchestrator:
    async def script(_agent, context):
        budget.consume(1)
        workspace = Path(str(context.workspace_path))
        if "Architecture" in context.target_work.title:
            (workspace / "architecture.md").write_text("Use a tiny deterministic service boundary.\n", encoding="utf-8")
            output = "architecture artifact prepared"
        else:
            (workspace / "solution.txt").write_text("BARN_BENCH_OK\n", encoding="utf-8")
            output = "implementation artifact prepared"
        return AgentResult(
            output=output,
            session_id=f"synthetic-{context.agent.id}",
            total_cost_usd=0.01,
            total_credits=1.0,
            num_turns=1,
            metadata={"provider": "synthetic"},
        )

    return BarnOrchestrator(
        engine=engine,
        workspace_manager=GitWorkspaceManager(repo),
        runtime=ScriptedRuntime(script),
    )


async def _attach_and_resolve(
    engine: BarnEngine,
    execution,
    work_id: str,
    agent_id: str,
    relative_path: str,
    command_prefix: str,
) -> None:
    path = Path(execution.workspace_path) / relative_path
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    await engine.submit_artifact(
        execution.run_id,
        agent_id=agent_id,
        work_id=work_id,
        kind="design" if relative_path.endswith(".md") else "code",
        uri=f"file://{path}",
        content_hash=digest,
        command_id=f"{command_prefix}-artifact",
    )
    await engine.resolve_work(
        execution.run_id,
        actor_agent_id=agent_id,
        work_id=work_id,
        command_id=f"{command_prefix}-resolve",
    )


async def _result(
    engine: BarnEngine,
    repo: Path,
    run_id: str,
    policy: str,
    turn_budget: int,
    final_workspace: str,
) -> PolicyResult:
    del repo
    state = await engine.store.get_run(run_id)
    events = await engine.store.list_events(run_id)
    metrics = summarize_run(state, events)
    audit = await audit_run(engine.store, run_id)
    solution_path = Path(final_workspace) / "solution.txt"
    passed = solution_path.exists() and solution_path.read_bytes() == b"BARN_BENCH_OK\n"
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


def _init_fixture_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init")
    _git(repo, "config", "user.email", "barn-benchmark@example.test")
    _git(repo, "config", "user.name", "Barn Benchmark")
    (repo / "TASK.md").write_text(
        "Produce solution.txt containing exactly BARN_BENCH_OK followed by a newline.\n",
        encoding="utf-8",
    )
    _git(repo, "add", "TASK.md")
    _git(repo, "commit", "-m", "benchmark fixture")


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()
