from datetime import datetime, timezone

from barn.domain import Agent, Artifact, ExecutionRecord, RunState, Verification, WorkItem, WorkStatus
from barn.neo4j_store import Neo4jGraphStore


class FakeDriver:
    def __init__(self):
        self.calls = []

    async def execute_query(self, query, parameters_=None, **kwargs):
        self.calls.append((query, parameters_ or {}, kwargs))
        return ([], None, [])

    async def close(self):
        pass


async def test_projection_uses_fixed_cypher_structure_and_parameterizes_model_strings():
    driver = FakeDriver()
    store = Neo4jGraphStore(driver, database="neo4j")
    malicious = "CRDT Specialist'}) MATCH (n) DETACH DELETE n //"
    state = RunState(id="run-1", goal="Goal", max_active_agents=4)
    state.work_items["work-1"] = WorkItem(
        id="work-1",
        run_id="run-1",
        title="Conflict resolution",
        status=WorkStatus.ACTIVE,
        required_capabilities={"crdt"},
        assigned_agent_id="agent-1",
    )
    state.agents["agent-1"] = Agent(
        id="agent-1",
        run_id="run-1",
        role=malicious,
        capabilities={"crdt"},
        spawned_because_work_id="work-1",
        assigned_work_ids={"work-1"},
    )
    state.artifacts["artifact-1"] = Artifact(
        id="artifact-1",
        run_id="run-1",
        work_id="work-1",
        producer_agent_id="agent-1",
        kind="design",
        uri="artifact://design",
        content_hash="abc",
    )
    state.verifications["verification-1"] = Verification(
        id="verification-1",
        run_id="run-1",
        artifact_id="artifact-1",
        verifier_agent_id="agent-2",
        passed=True,
        evidence="checked",
    )

    await store.project_run(state)

    joined_queries = "\n".join(call[0] for call in driver.calls)
    all_parameters = repr([call[1] for call in driver.calls])
    assert malicious not in joined_queries
    assert malicious in all_parameters
    assert "[:HAS_AGENT]" in joined_queries
    assert "[:HAS_WORK]" in joined_queries
    assert "[:SPAWNED_BECAUSE]" in joined_queries
    assert "[:PRODUCED_FOR]" in joined_queries
    assert "[:VERIFIES]" in joined_queries
    assert all(call[2]["database_"] == "neo4j" for call in driver.calls)


def test_module_import_does_not_require_neo4j_dependency():
    # Import happened at module collection. The optional dependency is only required
    # by Neo4jGraphStore.connect(), keeping the reference runtime usable offline.
    assert Neo4jGraphStore.__name__ == "Neo4jGraphStore"


async def test_projection_materializes_dependency_and_execution_relationships():
    driver = FakeDriver()
    store = Neo4jGraphStore(driver, database="neo4j")
    state = RunState(id="run-projection", goal="Build system", max_active_agents=4)
    state.agents["agent-1"] = Agent(
        id="agent-1",
        run_id=state.id,
        role="Builder",
        capabilities={"python"},
        assigned_work_ids={"work-2"},
    )
    state.work_items["work-1"] = WorkItem(
        id="work-1",
        run_id=state.id,
        title="Define interface",
        status=WorkStatus.RESOLVED,
    )
    state.work_items["work-2"] = WorkItem(
        id="work-2",
        run_id=state.id,
        title="Implement interface",
        status=WorkStatus.ACTIVE,
        dependency_ids={"work-1"},
        assigned_agent_id="agent-1",
    )
    now = datetime.now(timezone.utc)
    state.executions["exec-1"] = ExecutionRecord(
        id="exec-1",
        run_id=state.id,
        agent_id="agent-1",
        work_id="work-2",
        workspace_path="/tmp/barn/worktree",
        workspace_branch="barn/run/agent",
        runtime_session_id="session-1",
        output_summary="implemented",
        total_cost_usd=0.03,
        total_credits=4,
        num_turns=2,
        started_at=now,
        ended_at=now,
        duration_seconds=0.2,
        created_seq=7,
    )

    await store.project_run(state)

    joined_queries = "\n".join(call[0] for call in driver.calls)
    params = [call[1] for call in driver.calls]
    assert "[:DEPENDS_ON]" in joined_queries
    assert "[:HAS_EXECUTION]" in joined_queries
    assert "[:EXECUTED_BY]" in joined_queries
    assert "[:EXECUTED_WORK]" in joined_queries
    assert any(
        {"work": "work-2", "dependency": "work-1"} in call.get("edges", [])
        for call in params
    )
    execution_payloads = [item for call in params for item in call.get("executions", [])]
    assert any(item["id"] == "exec-1" and item["runtime_session_id"] == "session-1" for item in execution_payloads)


async def test_initialize_creates_execution_uniqueness_constraint():
    driver = FakeDriver()
    store = Neo4jGraphStore(driver, database="neo4j")

    await store.initialize()

    joined_queries = "\n".join(call[0] for call in driver.calls)
    assert "barn_execution_key" in joined_queries
    assert "BarnExecution" in joined_queries
