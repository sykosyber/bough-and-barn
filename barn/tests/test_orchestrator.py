from pathlib import Path
import subprocess

import pytest

from barn.domain import WorkStatus
from barn.engine import BarnEngine
from barn.orchestrator import BarnOrchestrator
from barn.runtime import AgentResult, ScriptedRuntime
from barn.store import InMemoryGraphStore
from barn.workspace import GitWorkspaceManager


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "project"
    repo.mkdir()
    git(repo, "init")
    git(repo, "config", "user.email", "barn@example.test")
    git(repo, "config", "user.name", "Barn Test")
    (repo / "README.md").write_text("base\n")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "initial")
    return repo


@pytest.mark.asyncio
async def test_orchestrator_executes_assigned_work_in_agent_worktree_but_does_not_resolve_it(git_repo: Path):
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Implement parser",
        chief_capabilities={"python"},
        command_id="run",
        run_id="run-orchestrator",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))

    async def script(agent, context):
        assert context.workspace_path is not None
        path = Path(context.workspace_path) / "parser.py"
        path.write_text("def parse(value):\n    return value\n")
        return AgentResult(output="Implemented parser", session_id="session-1", total_credits=3, num_turns=2)

    orchestrator = BarnOrchestrator(
        engine=engine,
        workspace_manager=GitWorkspaceManager(git_repo),
        runtime=ScriptedRuntime(script),
    )

    record = await orchestrator.execute_work(
        run_id=run.id,
        agent_id=chief.id,
        work_id=root.id,
        budget={"max_turns": 4},
        command_id="execute-root",
    )

    assert record.agent_id == chief.id
    assert record.work_id == root.id
    assert record.runtime_session_id == "session-1"
    assert record.total_credits == 3
    assert Path(record.workspace_path, "parser.py").exists()

    final = await store.get_run(run.id)
    assert record.id in final.executions
    assert final.work_items[root.id].status == WorkStatus.ACTIVE
    assert final.artifacts == {}
    events = await store.list_events(run.id)
    assert events[-1].type == "runtime.completed"
    assert events[-1].payload["execution_id"] == record.id


@pytest.mark.asyncio
async def test_runtime_failure_does_not_create_success_record_or_resolve_work(git_repo: Path):
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Implement parser",
        chief_capabilities={"python"},
        command_id="run",
        run_id="run-runtime-failure",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))

    async def fail(_agent, _context):
        raise RuntimeError("model unavailable")

    orchestrator = BarnOrchestrator(
        engine=engine,
        workspace_manager=GitWorkspaceManager(git_repo),
        runtime=ScriptedRuntime(fail),
    )

    with pytest.raises(RuntimeError, match="model unavailable"):
        await orchestrator.execute_work(
            run_id=run.id,
            agent_id=chief.id,
            work_id=root.id,
            command_id="execute-root",
        )

    final = await store.get_run(run.id)
    assert final.executions == {}
    assert final.work_items[root.id].status == WorkStatus.ACTIVE
    events = await store.list_events(run.id)
    assert [event.type for event in events] == ["run.created"]


@pytest.mark.asyncio
async def test_orchestrator_refuses_assigned_work_with_unresolved_dependencies(git_repo: Path):
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Build service",
        chief_capabilities={"python"},
        command_id="run",
        run_id="run-blocked-execution",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    dependency = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Define contract",
        command_id="dependency",
    )
    blocked = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implement contract",
        required_capabilities={"python"},
        dependency_ids={dependency.id},
        command_id="blocked",
    )
    current = await store.get_run(run.id)
    current.work_items[blocked.id].assigned_agent_id = chief.id
    current.agents[chief.id].assigned_work_ids.add(blocked.id)
    await store.save_run(current, expected_version=current.version)

    orchestrator = BarnOrchestrator(
        engine=engine,
        workspace_manager=GitWorkspaceManager(git_repo),
        runtime=ScriptedRuntime(lambda _agent, _context: AgentResult(output="should not run")),
    )

    with pytest.raises(Exception, match="work_dependencies_unresolved"):
        await orchestrator.execute_work(
            run_id=run.id,
            agent_id=chief.id,
            work_id=blocked.id,
            command_id="execute-blocked",
        )

    assert orchestrator.runtime.calls == []

@pytest.mark.asyncio
async def test_orchestrator_materializes_hash_verified_dependency_artifacts_into_worker_workspace(git_repo: Path):
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Build service",
        chief_capabilities={"architecture"},
        command_id="run",
        run_id="run-artifact-materialization",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    architecture = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Define architecture",
        required_capabilities={"architecture"},
        parent_work_id=root.id,
        command_id="architecture",
    )
    await engine.assign_work(
        run.id,
        agent_id=chief.id,
        work_id=architecture.id,
        command_id="assign-architecture",
    )

    manager = GitWorkspaceManager(git_repo)
    producer_workspace = manager.prepare(run_id=run.id, agent_id=chief.id)
    source = producer_workspace.path / "architecture.md"
    source.write_text("bounded event-driven design\n", encoding="utf-8")
    import hashlib

    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    await engine.submit_artifact(
        run.id,
        agent_id=chief.id,
        work_id=architecture.id,
        kind="design",
        uri=f"file://{source}",
        content_hash=digest,
        command_id="architecture-artifact",
    )
    await engine.resolve_work(
        run.id,
        actor_agent_id=chief.id,
        work_id=architecture.id,
        command_id="resolve-architecture",
    )

    implementation = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implement architecture",
        required_capabilities={"python"},
        parent_work_id=root.id,
        dependency_ids={architecture.id},
        command_id="implementation",
    )
    builder = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=implementation.id,
        capability="python",
        role="Builder",
        reason="implementation capability gap",
        command_id="builder",
    )

    async def script(_agent, context):
        assert len(context.artifacts) == 1
        local_uri = context.artifacts[0].uri
        assert local_uri.startswith("file://")
        local_path = Path(local_uri[7:])
        assert local_path.is_relative_to(Path(context.workspace_path))
        assert ".barn/context/artifacts" in local_path.as_posix()
        assert local_path.read_text(encoding="utf-8") == "bounded event-driven design\n"
        assert hashlib.sha256(local_path.read_bytes()).hexdigest() == context.artifacts[0].content_hash
        return AgentResult(output="used dependency artifact")

    orchestrator = BarnOrchestrator(
        engine=engine,
        workspace_manager=manager,
        runtime=ScriptedRuntime(script),
    )
    await orchestrator.execute_work(
        run_id=run.id,
        agent_id=str(builder.agent_id),
        work_id=implementation.id,
        command_id="execute-implementation",
    )

@pytest.mark.asyncio
async def test_orchestrator_rejects_dependency_artifact_when_committed_hash_no_longer_matches(git_repo: Path):
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    run = await engine.create_run(
        goal="Build service",
        chief_capabilities={"architecture"},
        command_id="run",
        run_id="run-artifact-integrity",
    )
    chief = next(iter(run.agents.values()))
    root = next(iter(run.work_items.values()))
    dependency = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Define contract",
        required_capabilities={"architecture"},
        parent_work_id=root.id,
        command_id="dependency",
    )
    await engine.assign_work(
        run.id,
        agent_id=chief.id,
        work_id=dependency.id,
        command_id="assign-dependency",
    )
    manager = GitWorkspaceManager(git_repo)
    producer_workspace = manager.prepare(run_id=run.id, agent_id=chief.id)
    source = producer_workspace.path / "contract.md"
    source.write_text("version one\n", encoding="utf-8")
    import hashlib

    original_digest = hashlib.sha256(source.read_bytes()).hexdigest()
    await engine.submit_artifact(
        run.id,
        agent_id=chief.id,
        work_id=dependency.id,
        kind="design",
        uri=f"file://{source}",
        content_hash=original_digest,
        command_id="dependency-artifact",
    )
    await engine.resolve_work(
        run.id,
        actor_agent_id=chief.id,
        work_id=dependency.id,
        command_id="resolve-dependency",
    )
    source.write_text("tampered after commit\n", encoding="utf-8")

    implementation = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Implement contract",
        required_capabilities={"python"},
        dependency_ids={dependency.id},
        command_id="implementation",
    )
    builder = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=implementation.id,
        capability="python",
        role="Builder",
        reason="implementation gap",
        command_id="builder",
    )
    orchestrator = BarnOrchestrator(
        engine=engine,
        workspace_manager=manager,
        runtime=ScriptedRuntime(lambda _agent, _context: AgentResult(output="must not run")),
    )

    with pytest.raises(Exception, match="artifact_integrity_failed"):
        await orchestrator.execute_work(
            run_id=run.id,
            agent_id=str(builder.agent_id),
            work_id=implementation.id,
            command_id="execute-implementation",
        )

    assert orchestrator.runtime.calls == []
