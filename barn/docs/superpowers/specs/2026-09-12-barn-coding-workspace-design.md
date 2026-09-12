# Barn Coding Workspace Extension Design

## Purpose

Extend Barn v0 from an inspectable organization kernel into a usable coding instrument without weakening the central invariant that Barn owns organization state. Each logical coding agent receives an isolated Git worktree and executes only work explicitly assigned by Barn. The host orchestrator prepares context and workspace, invokes an `AgentRuntime`, and records execution outcomes without treating model prose as completion evidence.

## Scope

This extension adds:

1. a deterministic Git workspace manager;
2. explicit assignment for existing compatible agents;
3. a host orchestrator that dispatches one assigned WorkItem to one AgentRuntime;
4. durable execution audit records/events and simple measured metrics.

It does not merge branches automatically, deploy code, infer correctness from model output, or let workers create hidden worktrees/subagents.

## Workspace model

Each non-retired agent may own one workspace rooted under a Barn-managed directory:

`<repo>/.barn/worktrees/<run-slug>/<agent-slug>`

with a branch:

`barn/<run-slug>/<agent-slug>`.

The workspace manager validates the repository, base ref, and branch/path ownership. It creates worktrees with native `git worktree add`, never by copying directories. Repeated preparation for the same `(run, agent)` is idempotent and returns the same workspace if it still exists.

Worktree metadata is host-side runtime metadata rather than part of the conceptual organization graph. Barn records workspace-prepared execution events, while Git remains authoritative for branch/commit state.

## Assignment

A ready WorkItem may be assigned to an existing non-retired agent when all declared required capabilities are included in that agent's capabilities and dependencies are resolved. Assignment is an explicit transition and event. Assignment is idempotent by command id.

Barn does not silently overload an agent with a second unresolved active assignment in this extension. A busy compatible specialist therefore cannot be reused for a second conflicting work item; a specialist request may spawn another agent if budget allows.

## Execution

`BarnOrchestrator.execute_work` requires an already-assigned work item. It:

1. loads state and validates agent/work assignment;
2. prepares/reuses the agent Git worktree;
3. builds a bounded `ContextPack`;
4. invokes an injected `AgentRuntime` using that worktree as host execution context;
5. records an `ExecutionRecord` and `runtime.completed` event with session/cost/credits/turn metadata;
6. returns the execution record.

Model output is not an Artifact. Work remains unresolved until an explicit artifact is submitted through the existing Barn transition boundary and, when configured, independently verified.

## Execution records

An `ExecutionRecord` contains:

- id, run_id, agent_id, work_id;
- workspace path and branch;
- runtime session id;
- output summary;
- total cost/credits/turns when available;
- start/end timestamps and duration;
- event sequence.

RunState stores records so API/metrics can inspect them. Neo4j projection may be added later; canonical `state_json` already preserves the records once the model is extended.

## Metrics

A pure metrics function summarizes a run without external inference:

- total/active/retired agents;
- work counts by status;
- artifacts and verifications;
- specialist spawn/reuse/reject counts from events;
- runtime executions;
- cumulative reported runtime cost/credits/turns;
- total recorded runtime seconds.

These are descriptive measurements, not evidence that Barn outperforms a baseline.

## Safety and failure semantics

- Workspace paths are derived from sanitized Barn IDs, never arbitrary model paths.
- Git subprocesses use argument arrays, not shell interpolation.
- A dirty source checkout does not prevent worktree creation, but Barn never auto-commits or auto-merges host changes.
- Runtime exceptions are surfaced and do not mark work resolved.
- Execution records are written only for completed runtime calls in this first slice; failed-attempt recording can be added as a separate event type later.
- Qoder's own worktree tools remain hidden because Barn owns workspace isolation.
