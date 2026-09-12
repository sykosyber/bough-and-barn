import pytest

from barn.engine import BarnEngine, SpecialistOutcome, TransitionError
from barn.qoder_tools import BarnToolService, QoderToolDependencyError, create_barn_mcp_server
from barn.store import InMemoryGraphStore


@pytest.mark.asyncio
async def test_bound_tool_service_can_create_work_and_license_specialist():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    state = await engine.create_run(
        goal="Build editor",
        chief_capabilities={"generalist"},
        command_id="run",
        run_id="run-tools",
    )
    chief = next(iter(state.agents.values()))
    root = next(iter(state.work_items.values()))
    service = BarnToolService(engine=engine, run_id=state.id, agent_id=chief.id, target_work_id=root.id, readable_work_ids={root.id})

    created = await service.propose_work(
        title="Resolve concurrent edits",
        description="Specify deterministic merge semantics",
        required_capabilities=["crdt"],
        parent_work_id=root.id,
        dependency_ids=[],
        requires_verification=True,
        priority=5,
        command_id="tool-work",
    )
    work_id = created["work"]["id"]

    decision = await service.request_specialist(
        work_id=work_id,
        capability="crdt",
        role="CRDT Specialist",
        reason="The work graph exposes a CRDT capability gap",
        command_id="tool-spawn",
    )

    assert decision["decision"]["outcome"] == SpecialistOutcome.SPAWNED
    snapshot = await service.get_context()
    assert work_id in {item["id"] for item in snapshot["work_items"]}
    assert snapshot["agent"]["id"] == chief.id


@pytest.mark.asyncio
async def test_bound_tool_service_submit_artifact_uses_bound_agent_identity():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    state = await engine.create_run(
        goal="Build parser",
        chief_capabilities={"python"},
        command_id="run",
        run_id="run-artifact-tool",
    )
    chief = next(iter(state.agents.values()))
    root = next(iter(state.work_items.values()))
    service = BarnToolService(engine=engine, run_id=state.id, agent_id=chief.id, target_work_id=root.id, readable_work_ids={root.id})

    result = await service.submit_artifact(
        work_id=root.id,
        kind="code",
        uri="file://parser.py",
        content_hash="abc123",
        command_id="artifact",
    )

    assert result["artifact"]["producer_agent_id"] == chief.id
    assert result["artifact"]["work_id"] == root.id


def test_qoder_mcp_factory_is_lazy_when_sdk_is_missing():
    store = InMemoryGraphStore()
    service = BarnToolService(engine=BarnEngine(store), run_id="run", agent_id="agent", target_work_id="work", readable_work_ids={"work"})

    with pytest.raises(QoderToolDependencyError):
        create_barn_mcp_server(service)

@pytest.mark.asyncio
async def test_tool_service_rejects_cross_branch_work_ids_and_hides_siblings():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    state = await engine.create_run(
        goal="Build editor",
        chief_capabilities={"generalist"},
        command_id="run",
        run_id="run-tool-scope",
    )
    chief = next(iter(state.agents.values()))
    root = next(iter(state.work_items.values()))
    visible = await engine.add_work(
        state.id,
        actor_agent_id=chief.id,
        title="Visible branch",
        description="Owned branch",
        required_capabilities={"crdt"},
        parent_work_id=root.id,
        dependency_ids=set(),
        requires_verification=False,
        priority=1,
        command_id="visible",
    )
    hidden = await engine.add_work(
        state.id,
        actor_agent_id=chief.id,
        title="Hidden sibling",
        description="Must remain outside the worker capability",
        required_capabilities={"security"},
        parent_work_id=root.id,
        dependency_ids=set(),
        requires_verification=False,
        priority=1,
        command_id="hidden",
    )
    service = BarnToolService(
        engine=engine,
        run_id=state.id,
        agent_id=chief.id,
        target_work_id=visible.id,
        readable_work_ids={root.id, visible.id},
    )

    context = await service.get_context()
    assert {item["id"] for item in context["work_items"]} == {root.id, visible.id}
    assert hidden.id not in {item["id"] for item in context["work_items"]}

    with pytest.raises(TransitionError, match="tool_work_out_of_scope"):
        await service.request_specialist(
            work_id=hidden.id,
            capability="security",
            role="Security Specialist",
            reason="Try to escape the branch",
            command_id="escape-spawn",
        )

    with pytest.raises(TransitionError, match="tool_work_out_of_scope"):
        await service.submit_artifact(
            work_id=hidden.id,
            kind="code",
            uri="file://escape.py",
            content_hash="escape",
            command_id="escape-artifact",
        )

    with pytest.raises(TransitionError, match="tool_work_out_of_scope"):
        await service.propose_work(
            title="Cross-branch child",
            description="Should not attach to sibling",
            required_capabilities=[],
            parent_work_id=hidden.id,
            dependency_ids=[],
            requires_verification=False,
            priority=0,
            command_id="escape-work",
        )


@pytest.mark.asyncio
async def test_tool_service_may_extend_its_own_branch_and_use_new_work():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    state = await engine.create_run(
        goal="Build editor",
        chief_capabilities={"generalist"},
        command_id="run",
        run_id="run-tool-owned-child",
    )
    chief = next(iter(state.agents.values()))
    root = next(iter(state.work_items.values()))
    service = BarnToolService(
        engine=engine,
        run_id=state.id,
        agent_id=chief.id,
        target_work_id=root.id,
        readable_work_ids={root.id},
    )

    created = await service.propose_work(
        title="CRDT decision",
        description="Resolve merge semantics",
        required_capabilities=["crdt"],
        parent_work_id=root.id,
        dependency_ids=[],
        requires_verification=False,
        priority=2,
        command_id="child",
    )
    child_id = created["work"]["id"]

    decision = await service.request_specialist(
        work_id=child_id,
        capability="crdt",
        role="CRDT Specialist",
        reason="New local obligation requires CRDT expertise",
        command_id="child-specialist",
    )

    assert decision["decision"]["outcome"] == SpecialistOutcome.SPAWNED
    context = await service.get_context()
    assert child_id in {item["id"] for item in context["work_items"]}


def test_barn_mcp_factory_derives_scope_from_dispatched_context(monkeypatch):
    from barn.domain import Agent, WorkItem
    from barn.qoder_tools import make_barn_mcp_server_factory
    from barn.runtime import ContextPack

    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    agent = Agent(id="agent-1", run_id="run-1", role="Builder", capabilities={"python"})
    root = WorkItem(id="root", run_id="run-1", title="Root")
    target = WorkItem(id="target", run_id="run-1", title="Target", parent_work_id="root")
    context = ContextPack(
        run_id="run-1",
        agent=agent,
        target_work=target,
        work_items=[root, target],
        artifacts=[],
    )
    captured = {}

    def fake_create(service):
        captured["service"] = service
        return "server"

    monkeypatch.setattr("barn.qoder_tools.create_barn_mcp_server", fake_create)
    factory = make_barn_mcp_server_factory(engine)

    server = factory("session-1", agent, context)

    assert server == "server"
    service = captured["service"]
    assert service.target_work_id == target.id
    assert service.readable_work_ids == {root.id, target.id}
    assert service.owned_work_ids == {target.id}
