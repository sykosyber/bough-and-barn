# Barn Coding Workspace Extension Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Barn agents isolated Git worktrees, explicit reusable-agent assignment, host-managed runtime dispatch, and descriptive execution metrics.

**Architecture:** Git remains authoritative for code workspaces while Barn remains authoritative for organization/work state. A `GitWorkspaceManager` creates one deterministic worktree per agent; `BarnOrchestrator` validates assignment, builds bounded context, invokes an injected `AgentRuntime`, and records runtime metadata without resolving work from model prose.

**Tech Stack:** Python standard library subprocess/pathlib, existing Barn kernel/runtime, Pydantic v2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-12-barn-coding-workspace-design.md`

## Global Constraints

- Barn owns workspace topology; workers cannot select arbitrary worktree paths.
- No automatic commit, merge, deployment, or work resolution from model output.
- One unresolved assignment per non-Chief specialist in this slice.
- Git commands use argv subprocess calls with no shell interpolation.
- Runtime execution uses already-assigned work and bounded ContextPack only.

---

### Task 1: Busy-specialist semantics and explicit assignment

**Files:**
- Modify: `src/barn/engine.py`
- Modify: `tests/test_engine_spawn.py`
- Create: `tests/test_engine_assignment.py`

**Produces:** `BarnEngine.assign_work`; specialist reuse only when compatible and not busy with another unresolved work item.

- [ ] Write failing tests for explicit compatible assignment and for a busy specialist not being reused for a different unresolved work item.
- [ ] Verify RED.
- [ ] Implement minimal assignment transition/event and reuse availability predicate.
- [ ] Verify GREEN and full suite.
- [ ] Commit.

### Task 2: Deterministic Git workspace manager

**Files:**
- Create: `src/barn/workspace.py`
- Create: `tests/test_workspace.py`

**Produces:** `GitWorkspace`, `GitWorkspaceManager.prepare`, `GitWorkspaceManager.status`.

- [ ] Write a failing test using a temporary initialized Git repo that prepares an agent worktree and proves a second prepare is idempotent.
- [ ] Verify RED.
- [ ] Implement sanitized deterministic path/branch generation and argv-only git calls.
- [ ] Add test that two agents receive distinct branches/worktrees and changes are isolated.
- [ ] Verify GREEN and commit.

### Task 3: Execution records and host orchestrator

**Files:**
- Modify: `src/barn/domain.py`
- Modify: `src/barn/store.py` only if required by model serialization
- Create: `src/barn/orchestrator.py`
- Create: `tests/test_orchestrator.py`

**Produces:** `ExecutionRecord`, `BarnOrchestrator.execute_work`.

- [ ] Write failing test with `ScriptedRuntime`: assigned work executes in the agent workspace and creates an execution record, but work remains unresolved.
- [ ] Verify RED.
- [ ] Implement record type and orchestrator.
- [ ] Add runtime failure test proving failure does not resolve work or create a successful execution record.
- [ ] Verify GREEN and commit.

### Task 4: Descriptive metrics and API exposure

**Files:**
- Create: `src/barn/metrics.py`
- Create: `tests/test_metrics.py`
- Modify: `src/barn/api.py`
- Modify: `tests/test_api.py`

**Produces:** `summarize_run(state, events)` and `GET /runs/{run_id}/metrics`.

- [ ] Write failing metric tests covering specialist decisions and runtime totals.
- [ ] Verify RED.
- [ ] Implement pure summary function and API endpoint.
- [ ] Verify full suite and commit.
