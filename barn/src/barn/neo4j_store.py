from __future__ import annotations

import json
import os
from typing import Any

from .domain import BarnEvent, RunState
from .store import RunAlreadyExistsError, RunNotFoundError


class Neo4jDependencyError(RuntimeError):
    pass


class Neo4jGraphStore:
    """Neo4j-backed Barn store with a canonical Run JSON record plus normalized graph projection.

    Barn owns all Cypher structure. User/model strings are passed only as query parameters.
    The engine serializes transitions per run; database constraints additionally protect event
    command identity when multiple processes are introduced later.
    """

    def __init__(self, driver: Any, *, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database

    @classmethod
    async def connect(
        cls,
        uri: str | None = None,
        user: str | None = None,
        password: str | None = None,
        *,
        database: str | None = None,
    ) -> "Neo4jGraphStore":
        try:
            from neo4j import AsyncGraphDatabase
        except ImportError as exc:
            raise Neo4jDependencyError(
                "Neo4j support requires `pip install 'barn-runtime[neo4j]'` or `pip install neo4j`."
            ) from exc
        uri = uri or os.environ.get("NEO4J_URI")
        user = user or os.environ.get("NEO4J_USER")
        password = password or os.environ.get("NEO4J_PASSWORD")
        database = database or os.environ.get("NEO4J_DATABASE", "neo4j")
        if not uri or not user or password is None:
            raise ValueError("NEO4J_URI, NEO4J_USER and NEO4J_PASSWORD are required")
        driver = AsyncGraphDatabase.driver(uri, auth=(user, password))
        await driver.verify_connectivity()
        store = cls(driver, database=database)
        await store.initialize()
        return store

    async def initialize(self) -> None:
        constraints = [
            "CREATE CONSTRAINT barn_run_id IF NOT EXISTS FOR (r:BarnRun) REQUIRE r.id IS UNIQUE",
            "CREATE CONSTRAINT barn_agent_key IF NOT EXISTS FOR (a:BarnAgent) REQUIRE (a.run_id, a.id) IS UNIQUE",
            "CREATE CONSTRAINT barn_work_key IF NOT EXISTS FOR (w:BarnWork) REQUIRE (w.run_id, w.id) IS UNIQUE",
            "CREATE CONSTRAINT barn_artifact_key IF NOT EXISTS FOR (a:BarnArtifact) REQUIRE (a.run_id, a.id) IS UNIQUE",
            "CREATE CONSTRAINT barn_verification_key IF NOT EXISTS FOR (v:BarnVerification) REQUIRE (v.run_id, v.id) IS UNIQUE",
            "CREATE CONSTRAINT barn_execution_key IF NOT EXISTS FOR (x:BarnExecution) REQUIRE (x.run_id, x.id) IS UNIQUE",
            "CREATE CONSTRAINT barn_event_command IF NOT EXISTS FOR (e:BarnEvent) REQUIRE (e.run_id, e.command_id) IS UNIQUE",
        ]
        for query in constraints:
            await self.driver.execute_query(query, database_=self.database)

    async def close(self) -> None:
        await self.driver.close()

    async def create_run(self, state: RunState) -> RunState:
        state_json = json.dumps(state.model_dump(mode="json"), sort_keys=True)
        query = """
        MERGE (r:BarnRun {id: $run_id})
        ON CREATE SET r.goal = $goal,
                      r.max_active_agents = $max_active_agents,
                      r.state_json = $state_json,
                      r.version = $version,
                      r.event_seq = 0,
                      r.created_at = $created_at,
                      r.created_marker = $created_marker
        RETURN r.state_json AS state_json, r.created_marker AS created_marker
        """
        marker = state.id + ":initial"
        result = await self.driver.execute_query(
            query,
            parameters_={
                "run_id": state.id,
                "goal": state.goal,
                "max_active_agents": state.max_active_agents,
                "state_json": state_json,
                "version": state.version,
                "created_at": state.created_at.isoformat(),
                "created_marker": marker,
            },
            database_=self.database,
        )
        records = _records(result)
        if not records:
            raise RuntimeError("Neo4j create_run returned no record")
        record = records[0]
        if _value(record, "created_marker") != marker or _value(record, "state_json") != state_json:
            raise RunAlreadyExistsError(state.id)
        await self.project_run(state)
        return state.model_copy(deep=True)

    async def get_run(self, run_id: str) -> RunState:
        result = await self.driver.execute_query(
            "MATCH (r:BarnRun {id: $run_id}) RETURN r.state_json AS state_json, r.version AS version",
            parameters_={"run_id": run_id},
            database_=self.database,
        )
        records = _records(result)
        if not records:
            raise RunNotFoundError(run_id)
        state = RunState.model_validate_json(_value(records[0], "state_json"))
        state.version = int(_value(records[0], "version"))
        return state

    async def save_run(self, state: RunState, expected_version: int | None = None) -> RunState:
        expected = state.version if expected_version is None else expected_version
        next_state = state.model_copy(deep=True)
        next_state.version = expected + 1
        state_json = json.dumps(next_state.model_dump(mode="json"), sort_keys=True)
        result = await self.driver.execute_query(
            """
            MATCH (r:BarnRun {id: $run_id})
            WHERE r.version = $expected_version
            SET r.state_json = $state_json,
                r.version = $next_version,
                r.goal = $goal,
                r.max_active_agents = $max_active_agents
            RETURN r.version AS version
            """,
            parameters_={
                "run_id": state.id,
                "expected_version": expected,
                "next_version": next_state.version,
                "state_json": state_json,
                "goal": state.goal,
                "max_active_agents": state.max_active_agents,
            },
            database_=self.database,
        )
        if not _records(result):
            current = await self.get_run(state.id)
            raise ValueError(
                f"version conflict for {state.id}: expected {expected}, actual {current.version}"
            )
        await self.project_run(next_state)
        return next_state

    async def append_event(self, event: BarnEvent) -> BarnEvent:
        existing = await self.get_event_by_command(event.run_id, event.command_id)
        if existing is not None:
            return existing
        payload = event.model_dump(mode="json")
        # BarnEngine serializes transitions per run. The unique event-command constraint
        # prevents duplicate command identity; a future multi-process scheduler should
        # move sequence allocation into an explicit Neo4j transaction/retry loop.
        result = await self.driver.execute_query(
            """
            MATCH (r:BarnRun {id: $run_id})
            SET r.event_seq = coalesce(r.event_seq, 0) + 1
            CREATE (e:BarnEvent {
                run_id: $run_id,
                command_id: $command_id,
                seq: r.event_seq,
                type: $type,
                actor_agent_id: $actor_agent_id,
                work_id: $work_id,
                event_json: $event_json,
                created_at: $created_at
            })
            MERGE (r)-[:HAS_EVENT]->(e)
            RETURN e.seq AS seq
            """,
            parameters_={
                "run_id": event.run_id,
                "command_id": event.command_id,
                "type": event.type,
                "actor_agent_id": event.actor_agent_id,
                "work_id": event.work_id,
                "event_json": json.dumps(payload, sort_keys=True),
                "created_at": event.created_at.isoformat(),
            },
            database_=self.database,
        )
        records = _records(result)
        if not records:
            raise RunNotFoundError(event.run_id)
        committed = event.model_copy(deep=True)
        committed.seq = int(_value(records[0], "seq"))
        # Rewrite JSON now that authoritative sequence is known.
        await self.driver.execute_query(
            """
            MATCH (e:BarnEvent {run_id: $run_id, command_id: $command_id})
            SET e.event_json = $event_json
            """,
            parameters_={
                "run_id": event.run_id,
                "command_id": event.command_id,
                "event_json": json.dumps(committed.model_dump(mode="json"), sort_keys=True),
            },
            database_=self.database,
        )
        return committed

    async def list_events(self, run_id: str) -> list[BarnEvent]:
        result = await self.driver.execute_query(
            """
            MATCH (:BarnRun {id: $run_id})-[:HAS_EVENT]->(e:BarnEvent)
            RETURN e.event_json AS event_json
            ORDER BY e.seq ASC
            """,
            parameters_={"run_id": run_id},
            database_=self.database,
        )
        return [BarnEvent.model_validate_json(_value(record, "event_json")) for record in _records(result)]

    async def get_event_by_command(self, run_id: str, command_id: str) -> BarnEvent | None:
        result = await self.driver.execute_query(
            """
            MATCH (e:BarnEvent {run_id: $run_id, command_id: $command_id})
            RETURN e.event_json AS event_json
            """,
            parameters_={"run_id": run_id, "command_id": command_id},
            database_=self.database,
        )
        records = _records(result)
        if not records:
            return None
        return BarnEvent.model_validate_json(_value(records[0], "event_json"))

    async def project_run(self, state: RunState) -> None:
        data = state.model_dump(mode="json")
        await self._query(
            """
            MERGE (r:BarnRun {id: $run_id})
            SET r.goal = $goal, r.max_active_agents = $max_active_agents
            """,
            {"run_id": state.id, "goal": state.goal, "max_active_agents": state.max_active_agents},
        )
        await self._query(
            """
            MATCH (r:BarnRun {id: $run_id})
            UNWIND $agents AS item
            MERGE (a:BarnAgent {run_id: $run_id, id: item.id})
            SET a += item
            MERGE (r)-[:HAS_AGENT]->(a)
            """,
            {"run_id": state.id, "agents": list(data["agents"].values())},
        )
        await self._query(
            """
            MATCH (r:BarnRun {id: $run_id})
            UNWIND $work_items AS item
            MERGE (w:BarnWork {run_id: $run_id, id: item.id})
            SET w += item
            MERGE (r)-[:HAS_WORK]->(w)
            """,
            {"run_id": state.id, "work_items": list(data["work_items"].values())},
        )
        await self._query(
            """
            MATCH (:BarnRun {id: $run_id})-[:HAS_AGENT]->(a:BarnAgent)
            OPTIONAL MATCH (a)-[old:ASSIGNED_TO]->(:BarnWork {run_id: $run_id})
            DELETE old
            """,
            {"run_id": state.id},
        )
        parent_edges = [
            {"parent": work.parent_work_id, "child": work.id}
            for work in state.work_items.values()
            if work.parent_work_id
        ]
        await self._query(
            """
            UNWIND $edges AS edge
            MATCH (parent:BarnWork {run_id: $run_id, id: edge.parent})
            MATCH (child:BarnWork {run_id: $run_id, id: edge.child})
            MERGE (parent)-[:PARENT_OF]->(child)
            """,
            {"run_id": state.id, "edges": parent_edges},
        )
        await self._query(
            """
            MATCH (:BarnRun {id: $run_id})-[:HAS_WORK]->(w:BarnWork)
            OPTIONAL MATCH (w)-[old:DEPENDS_ON]->(:BarnWork {run_id: $run_id})
            DELETE old
            """,
            {"run_id": state.id},
        )
        dependency_edges = [
            {"work": work.id, "dependency": dependency_id}
            for work in state.work_items.values()
            for dependency_id in sorted(work.dependency_ids)
        ]
        await self._query(
            """
            UNWIND $edges AS edge
            MATCH (w:BarnWork {run_id: $run_id, id: edge.work})
            MATCH (dependency:BarnWork {run_id: $run_id, id: edge.dependency})
            MERGE (w)-[:DEPENDS_ON]->(dependency)
            """,
            {"run_id": state.id, "edges": dependency_edges},
        )
        assignment_edges = [
            {"agent": work.assigned_agent_id, "work": work.id}
            for work in state.work_items.values()
            if work.assigned_agent_id
        ]
        await self._query(
            """
            UNWIND $edges AS edge
            MATCH (a:BarnAgent {run_id: $run_id, id: edge.agent})
            MATCH (w:BarnWork {run_id: $run_id, id: edge.work})
            MERGE (a)-[:ASSIGNED_TO]->(w)
            """,
            {"run_id": state.id, "edges": assignment_edges},
        )
        spawn_edges = [
            {"agent": agent.id, "work": agent.spawned_because_work_id}
            for agent in state.agents.values()
            if agent.spawned_because_work_id
        ]
        await self._query(
            """
            UNWIND $edges AS edge
            MATCH (a:BarnAgent {run_id: $run_id, id: edge.agent})
            MATCH (w:BarnWork {run_id: $run_id, id: edge.work})
            MERGE (a)-[:SPAWNED_BECAUSE]->(w)
            """,
            {"run_id": state.id, "edges": spawn_edges},
        )
        await self._query(
            """
            MATCH (r:BarnRun {id: $run_id})
            UNWIND $artifacts AS item
            MERGE (artifact:BarnArtifact {run_id: $run_id, id: item.id})
            SET artifact += item
            MERGE (r)-[:HAS_ARTIFACT]->(artifact)
            WITH artifact, item
            MATCH (w:BarnWork {run_id: $run_id, id: item.work_id})
            MERGE (artifact)-[:PRODUCED_FOR]->(w)
            """,
            {"run_id": state.id, "artifacts": list(data["artifacts"].values())},
        )
        await self._query(
            """
            MATCH (r:BarnRun {id: $run_id})
            UNWIND $verifications AS item
            MERGE (v:BarnVerification {run_id: $run_id, id: item.id})
            SET v += item
            MERGE (r)-[:HAS_VERIFICATION]->(v)
            WITH v, item
            MATCH (artifact:BarnArtifact {run_id: $run_id, id: item.artifact_id})
            MERGE (v)-[:VERIFIES]->(artifact)
            """,
            {"run_id": state.id, "verifications": list(data["verifications"].values())},
        )
        await self._query(
            """
            MATCH (r:BarnRun {id: $run_id})
            UNWIND $executions AS item
            MERGE (x:BarnExecution {run_id: $run_id, id: item.id})
            SET x += item
            MERGE (r)-[:HAS_EXECUTION]->(x)
            WITH x, item
            MATCH (a:BarnAgent {run_id: $run_id, id: item.agent_id})
            MERGE (x)-[:EXECUTED_BY]->(a)
            WITH x, item
            MATCH (w:BarnWork {run_id: $run_id, id: item.work_id})
            MERGE (x)-[:EXECUTED_WORK]->(w)
            """,
            {"run_id": state.id, "executions": list(data["executions"].values())},
        )

    async def _query(self, query: str, parameters: dict[str, Any]) -> Any:
        return await self.driver.execute_query(
            query,
            parameters_=parameters,
            database_=self.database,
        )


def _records(result: Any) -> list[Any]:
    if isinstance(result, tuple):
        return list(result[0])
    if hasattr(result, "records"):
        return list(result.records)
    try:
        return list(result)
    except TypeError:
        return []


def _value(record: Any, key: str) -> Any:
    if isinstance(record, dict):
        return record[key]
    return record[key]
