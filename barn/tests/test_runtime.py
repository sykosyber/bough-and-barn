import importlib

import pytest

from barn.engine import BarnEngine
from barn.runtime import build_context_pack
from barn.store import InMemoryGraphStore


@pytest.mark.asyncio
async def test_context_pack_excludes_unrelated_work_and_artifacts():
    store = InMemoryGraphStore()
    engine = BarnEngine(store)
    state = await engine.create_run(
        goal="Build editor",
        max_active_agents=4,
        chief_capabilities={"generalist"},
        command_id="run-1",
        run_id="run_ctx",
    )
    chief = next(iter(state.agents.values()))
    root = next(iter(state.work_items.values()))

    parent = await engine.add_work(
        state.id,
        actor_agent_id=chief.id,
        title="Realtime collaboration",
        command_id="work-parent",
        parent_work_id=root.id,
    )
    target = await engine.add_work(
        state.id,
        actor_agent_id=chief.id,
        title="Conflict resolution",
        command_id="work-target",
        parent_work_id=parent.id,
        required_capabilities={"crdt"},
    )
    dependency = await engine.add_work(
        state.id,
        actor_agent_id=chief.id,
        title="Persistence contract",
        command_id="work-dependency",
        parent_work_id=root.id,
    )
    unrelated = await engine.add_work(
        state.id,
        actor_agent_id=chief.id,
        title="Marketing site",
        command_id="work-unrelated",
        parent_work_id=root.id,
    )

    # Attach the dependency after creation so the pack has both an ancestor path and dependency path.
    current = await store.get_run(state.id)
    current.work_items[target.id].dependency_ids.add(dependency.id)
    await store.save_run(current, expected_version=current.version)

    decision = await engine.request_specialist(
        state.id,
        requesting_agent_id=chief.id,
        work_id=target.id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Need conflict semantics",
        command_id="spawn-crdt",
    )
    assert decision.agent_id is not None

    parent_artifact = await engine.submit_artifact(
        state.id,
        agent_id=chief.id,
        work_id=root.id,
        kind="brief",
        uri="memory://brief",
        content_hash="root-hash",
        command_id="artifact-root",
    )
    # Put the root back into active state for this context-selection test; the artifact itself is enough.
    current = await store.get_run(state.id)
    current.work_items[root.id].status = "active"
    current.agents[chief.id].assigned_work_ids.add(root.id)
    await store.save_run(current, expected_version=current.version)

    unrelated_artifact = await engine.submit_artifact(
        state.id,
        agent_id=chief.id,
        work_id=unrelated.id,
        kind="copy",
        uri="memory://marketing",
        content_hash="unrelated-hash",
        command_id="artifact-unrelated",
    )

    pack = await build_context_pack(
        store,
        run_id=state.id,
        agent_id=decision.agent_id,
        work_id=target.id,
        budget={"max_turns": 8, "remaining_agents": 2},
    )

    included_work_ids = {item.id for item in pack.work_items}
    assert target.id in included_work_ids
    assert parent.id in included_work_ids
    assert root.id in included_work_ids
    assert dependency.id in included_work_ids
    assert unrelated.id not in included_work_ids

    included_artifact_ids = {item.id for item in pack.artifacts}
    assert parent_artifact.id in included_artifact_ids
    assert unrelated_artifact.id not in included_artifact_ids
    assert pack.budget == {"max_turns": 8, "remaining_agents": 2}
    assert pack.agent.id == decision.agent_id
    assert pack.target_work.id == target.id


def test_qoder_adapter_import_is_lazy_and_session_mapping_is_stable():
    module = importlib.import_module("barn.qoder_runtime")
    runtime = module.QoderAgentRuntime(cwd="/tmp/barn")

    first = runtime.session_id_for("run-a", "agent-a")
    second = runtime.session_id_for("run-a", "agent-a")
    other = runtime.session_id_for("run-a", "agent-b")

    assert first == second
    assert first != other
    assert len(first) == 36


@pytest.mark.asyncio
async def test_qoder_dependency_error_occurs_only_when_runtime_executes():
    module = importlib.import_module("barn.qoder_runtime")
    runtime = module.QoderAgentRuntime(cwd="/tmp/barn")

    from barn.domain import Agent, WorkItem
    from barn.runtime import ContextPack

    agent = Agent(id="agent-1", run_id="run-1", role="Builder", capabilities={"python"})
    work = WorkItem(id="work-1", run_id="run-1", title="Implement parser")
    pack = ContextPack(
        run_id="run-1",
        agent=agent,
        target_work=work,
        work_items=[work],
        artifacts=[],
        budget={"max_turns": 2},
    )

    with pytest.raises(module.QoderDependencyError):
        await runtime.run(agent, pack)

@pytest.mark.asyncio
async def test_qoder_runtime_limits_visible_tools_and_resumes_same_agent_session(monkeypatch):
    import sys
    import types

    captured_options = []

    class FakeOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured_options.append(kwargs)

    class FakeResultMessage:
        def __init__(self, session_id):
            self.is_error = False
            self.session_id = session_id
            self.result = "done"
            self.total_cost_usd = 0.01
            self.total_credits = 2
            self.num_turns = 1

    async def fake_query(*, prompt, options):
        del prompt
        session_id = getattr(options, "session_id", None) or getattr(options, "resume", None)
        yield FakeResultMessage(session_id)

    fake_sdk = types.SimpleNamespace(
        QoderAgentOptions=FakeOptions,
        ResultMessage=FakeResultMessage,
        query=fake_query,
        qodercli_auth=lambda: "local-auth",
    )
    monkeypatch.setitem(sys.modules, "qoder_agent_sdk", fake_sdk)

    from barn.domain import Agent, WorkItem
    from barn.qoder_runtime import QoderAgentRuntime
    from barn.runtime import ContextPack

    agent = Agent(id="agent-q", run_id="run-q", role="Builder", capabilities={"python"})
    work = WorkItem(id="work-q", run_id="run-q", title="Implement parser")
    pack = ContextPack(
        run_id="run-q",
        agent=agent,
        target_work=work,
        work_items=[work],
        artifacts=[],
        budget={"max_turns": 3},
    )
    runtime = QoderAgentRuntime(cwd="/tmp/barn")

    await runtime.run(agent, pack)
    await runtime.run(agent, pack)

    expected_tools = ["Read", "Glob", "Grep", "Bash", "Edit", "Write"]
    assert captured_options[0]["tools"] == expected_tools
    assert captured_options[0]["allowed_tools"] == expected_tools
    assert captured_options[0]["auth"] == "local-auth"
    assert "session_id" in captured_options[0]
    assert "resume" not in captured_options[0]
    assert captured_options[1]["resume"] == captured_options[0]["session_id"]
    assert "session_id" not in captured_options[1]

@pytest.mark.asyncio
async def test_qoder_runtime_exposes_only_bounded_barn_context_tool(monkeypatch):
    import sys
    import types

    captured_options = []

    class FakeOptions:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            captured_options.append(kwargs)

    class FakeResultMessage:
        def __init__(self, session_id):
            self.is_error = False
            self.session_id = session_id
            self.result = "done"
            self.total_cost_usd = 0.0
            self.total_credits = 1
            self.num_turns = 1

    async def fake_query(*, prompt, options):
        del prompt
        session_id = getattr(options, "session_id", None) or getattr(options, "resume", None)
        yield FakeResultMessage(session_id)

    fake_sdk = types.SimpleNamespace(
        QoderAgentOptions=FakeOptions,
        ResultMessage=FakeResultMessage,
        query=fake_query,
        qodercli_auth=lambda: "local-auth",
    )
    monkeypatch.setitem(sys.modules, "qoder_agent_sdk", fake_sdk)

    from barn.domain import Agent, WorkItem
    from barn.qoder_runtime import QoderAgentRuntime
    from barn.runtime import ContextPack

    agent = Agent(id="agent-q", run_id="run-q", role="Builder", capabilities={"python"})
    work = WorkItem(id="work-q", run_id="run-q", title="Implement parser")
    pack = ContextPack(
        run_id="run-q",
        agent=agent,
        target_work=work,
        work_items=[work],
        artifacts=[],
    )
    runtime = QoderAgentRuntime(
        cwd="/tmp/barn",
        mcp_server_factory=lambda session_id, current_agent, context: {
            "session": session_id,
            "agent": current_agent.id,
            "work": context.target_work.id,
        },
    )

    await runtime.run(agent, pack)

    tools = captured_options[0]["tools"]
    assert "mcp__barn__get_context" in tools
    assert "mcp__barn__get_snapshot" not in tools
