# Barn Runtime Architecture

Barn is an artifact-conditioned organization runtime. The organization is explicit state, not a side effect of model conversation.

## Authority boundary

Only `BarnEngine` commits semantic organization changes. Worker runtimes may propose typed commands through the Barn capability surface, but they do not receive raw graph/database mutation access.

The semantic state is `RunState`:

- `Agent`: role, capabilities, lifecycle, assignments, spawn provenance.
- `WorkItem`: obligations, dependencies, required capabilities, verification requirements, status.
- `Artifact`: durable output bound to producer and work.
- `Verification`: independent evidence over an artifact.
- `ExecutionRecord`: one completed runtime invocation with workspace/session/cost metadata.
- `BarnEvent`: append-only transition record used for replay and audit.

`RunState.version` is persistence concurrency metadata and is excluded from semantic audit hashes.

## Execution path

A coding execution follows this path:

1. Scheduler derives ready work from committed dependencies.
2. Barn explicitly assigns work to a compatible, non-conflicting agent.
3. `GitWorkspaceManager` prepares one deterministic branch/worktree for that logical agent.
4. `build_context_pack` selects only target work, ancestors, dependency closure, and structurally relevant artifacts.
5. `BarnOrchestrator` invokes an injected `AgentRuntime` inside the worktree.
6. Runtime completion creates an `ExecutionRecord`; it does not resolve work.
7. A worker must separately submit a durable `Artifact` through Barn.
8. Verified work requires a passing verification from an agent other than the artifact producer.
9. Only then may work resolve and an otherwise-unneeded specialist retire.

## Qoder boundary

`QoderAgentRuntime` maps each `(run_id, agent_id)` to a stable Qoder session. Barn deliberately controls the Qoder-visible tool list. Native Qoder subagent creation is not exposed.

`make_barn_mcp_server_factory(engine)` derives a fresh in-process MCP service from the exact dispatched `ContextPack`:

- readable work = work IDs already present in the pack;
- mutable/owned work = the target work plus child work created through the service;
- siblings outside that capability are inaccessible;
- the global run snapshot is not exposed;
- `get_context` returns only the bounded structural neighborhood.

The model can request topology change only through `request_specialist`. Barn may spawn, reuse, or refuse.

## Git workspace ownership

Barn, not the model provider, owns code isolation. Each logical agent receives a deterministic Git worktree and branch. Git subprocesses use argv arrays rather than shell interpolation. Runtime output is not automatically committed or merged.

This means model-provider worktree/subagent features can be hidden without losing workspace isolation.

## Cross-worktree artifact materialization

Before dispatch, `BarnOrchestrator` copies only structurally relevant local artifacts from the bounded `ContextPack` into the receiving worker's own `.barn/context/artifacts/<artifact_id>/` directory. Barn recomputes SHA-256 from the source bytes and refuses dispatch on a mismatch with the committed artifact hash. The worker therefore consumes dependency bytes without receiving direct access to another agent's worktree. Non-local artifact URIs remain references and are not fetched implicitly.

## Persistence and Neo4j projection

`InMemoryGraphStore` is the semantic reference store. `Neo4jGraphStore` stores canonical `state_json` and projects normalized graph entities using fixed Cypher structure with parameters for model/user strings.

Projected relationships include:

- `BarnRun-[:HAS_AGENT]->BarnAgent`
- `BarnRun-[:HAS_WORK]->BarnWork`
- `BarnWork-[:PARENT_OF]->BarnWork`
- `BarnWork-[:DEPENDS_ON]->BarnWork`
- `BarnAgent-[:ASSIGNED_TO]->BarnWork`
- `BarnAgent-[:SPAWNED_BECAUSE]->BarnWork`
- `BarnRun-[:HAS_ARTIFACT]->BarnArtifact-[:PRODUCED_FOR]->BarnWork`
- `BarnRun-[:HAS_VERIFICATION]->BarnVerification-[:VERIFIES]->BarnArtifact`
- `BarnRun-[:HAS_EXECUTION]->BarnExecution`
- `BarnExecution-[:EXECUTED_BY]->BarnAgent`
- `BarnExecution-[:EXECUTED_WORK]->BarnWork`

Dependency edges are deleted and rebuilt during projection so Neo4j represents the current materialized dependency set rather than accumulating stale edges.

## Replay and audit

The event ledger is sufficient to reconstruct semantic `RunState` for all implemented transition types. `replay_run(events)` rejects missing, mixed-run, non-monotonic, or unknown event sequences.

`canonical_state_hash` recursively normalizes semantic state and hashes canonical JSON with SHA-256. Store `version` is intentionally excluded.

`GET /runs/{run_id}/audit` loads materialized state and the append-only ledger independently, replays the ledger from zero, hashes both semantic states, and returns:

- event count;
- materialized hash;
- replayed hash;
- equality result;
- replay error when reconstruction is invalid.

An audit mismatch is evidence that materialized state changed without an equivalent committed event or that replay semantics no longer agree with transition semantics.

## Failure semantics

- Model-runtime success does not imply task completion.
- Runtime exceptions do not create successful execution records or resolve work.
- Work cannot resolve without an artifact.
- Verification-gated work cannot resolve without independent passing evidence.
- A specialist cannot retire while unresolved work remains assigned.
- A specialist request cannot create a duplicate active agent when an idle compatible agent can be reused.
- Busy specialists are not treated as unlimited parallel capacity.
- Qoder workers cannot name sibling work outside their dispatched capability.

## Deferred mechanisms

Barn intentionally does not yet include stochastic/OSAHR online scheduling, learned topology policies, GraphRAG, automatic merging, production deployment, or autonomous acceptance of generated code. Those mechanisms are justified only after matched-budget experiments establish where simpler baselines fail.
