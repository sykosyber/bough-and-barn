# Barn v0 Design

## Purpose

Barn is an artifact-conditioned organization runtime for long-horizon software work. The v0 hypothesis is deliberately narrow: an unresolved work obligation may expose a capability gap; Barn may license a specialist only when that gap is explicit, budget permits it, and no existing active agent already satisfies the capability. Every organizational mutation must have a durable causal explanation rooted in work state.

## Non-goals

Barn v0 is not a general swarm framework, not an OSAHR stochastic scheduler, not GraphRAG, not a learned topology optimizer, and not a replacement for Qoder Experts Mode. It does not claim adaptive multi-agent topology is novel. It tests whether artifact-conditioned specialization produces useful, inspectable coordination.

## Architecture

The system has six boundaries:

1. **Domain kernel** — typed Agents, WorkItems, Artifacts, Verifications, Events, and transition requests.
2. **Transition engine** — the only component allowed to commit organizational mutations. Models can request transitions but never directly mutate state.
3. **Graph store** — an async persistence protocol with an in-memory reference implementation and a Neo4j implementation/projection.
4. **Scheduler** — deterministically exposes ready work and assigns it to compatible active agents. Spawning is a scarce-resource decision, not a default.
5. **Agent runtime adapter** — Qoder is a worker runtime. Barn owns the organization. Each logical Barn agent maps to an independent host-managed Qoder session.
6. **API/UI** — FastAPI endpoints expose snapshot, transitions, and causal "why" paths. A small browser UI renders work and crew graphs.

## Core invariants

- No specialist without an unresolved WorkItem that requires its capability.
- No spawn when an active compatible agent can be reused.
- No spawn above the configured active-agent budget.
- Every spawn records `spawned_because_work_id`, `requested_by_agent_id`, capability, and reason.
- An agent cannot resolve work without at least one artifact.
- Work configured as `requires_verification=True` cannot resolve without a passing verification of one of its artifacts.
- A specialist cannot retire while assigned unresolved work remains.
- Events are append-only, monotonically sequenced per run, and idempotent by command id.
- Models propose typed commands; only the transition engine validates and commits them.

## State model

### Agent

- `id`
- `run_id`
- `role`
- `capabilities: set[str]`
- `status: active | idle | retired`
- `parent_agent_id | None`
- `spawned_because_work_id | None`
- `spawn_reason | None`
- `runtime_session_id | None`
- `created_seq`
- `retired_seq | None`

### WorkItem

- `id`
- `run_id`
- `title`
- `description`
- `status: proposed | ready | active | blocked | review | resolved | cancelled`
- `required_capabilities: set[str]`
- `parent_work_id | None`
- `dependency_ids: set[str]`
- `assigned_agent_id | None`
- `requires_verification: bool`
- `priority: int`
- `created_seq`
- `resolved_seq | None`

### Artifact

- `id`
- `run_id`
- `work_id`
- `producer_agent_id`
- `kind`
- `uri`
- `content_hash`
- `created_seq`

### Verification

- `id`
- `run_id`
- `artifact_id`
- `verifier_agent_id`
- `passed`
- `evidence`
- `created_seq`

### Event

- `seq`
- `run_id`
- `command_id`
- `type`
- `actor_agent_id | None`
- `work_id | None`
- `payload`
- `created_at`

## Spawn licensing

A `RequestSpecialist` command contains a requesting agent, work item, desired capability, role label, and reason. The engine applies this order:

1. Reject if the work does not exist or is terminal.
2. Reject if the desired capability is not required by that work item.
3. Reuse an active compatible agent if one exists and is not already assigned conflicting active work.
4. Reject if active-agent budget is exhausted.
5. Otherwise create the specialist, bind it causally to the work item, and optionally assign the work.

The decision result is explicit: `spawned`, `reused`, or `rejected`, with machine-readable reason.

## Why-path semantics

`why_agent_exists(agent_id)` returns a stable causal chain assembled from committed state/events:

`Goal/ancestor work -> descendant work -> required capability -> specialist request -> agent`.

The explanation must not depend on asking a language model to retrospectively justify the spawn.

## Runtime integration

`AgentRuntime` is a protocol. `ScriptedRuntime` is used in tests/demo. `QoderAgentRuntime` is optional and lazily imports `qoder_agent_sdk`. A logical Barn agent receives a ContextPack consisting only of the current work item, ancestor decisions/artifacts, directly relevant dependencies, allowed tools, and budget metadata. It does not receive the entire global transcript by default.

Barn tools exposed to Qoder are typed transition requests such as `barn_request_specialist`, `barn_propose_work`, `barn_submit_artifact`, and `barn_report_blocker`. Their handlers call the Barn API/kernel; they never expose raw Neo4j mutation tools.

## Persistence

The in-memory store is the semantic reference implementation. The Neo4j adapter persists the same entities/relationships and event sequence. Neo4j relationship types are fixed by Barn code; dynamic labels or relationship types from model input are forbidden.

## API

- `POST /runs` — create a run and chief/generalist agent.
- `GET /runs/{run_id}/snapshot` — materialized graph snapshot.
- `POST /runs/{run_id}/work` — add child work.
- `POST /runs/{run_id}/specialists/request` — request/reuse/refuse specialist.
- `POST /runs/{run_id}/artifacts` — submit artifact.
- `POST /runs/{run_id}/verifications` — record verification.
- `POST /runs/{run_id}/work/{work_id}/resolve` — resolve under invariants.
- `POST /runs/{run_id}/agents/{agent_id}/retire` — retire under invariants.
- `GET /runs/{run_id}/agents/{agent_id}/why` — causal explanation.

## Evaluation

The first matched comparison uses the same task and inference budget across:

1. single generalist,
2. fixed specialist team,
3. manager-driven dynamic delegation,
4. Barn artifact-conditioned specialization.

Primary measurements: task success, total model tokens/cost, wall-clock time, spawned-agent count, rework count, verification failures, and unsupported/duplicate spawn rate. Barn is not considered successful merely because the graph looks compelling.
