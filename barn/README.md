# Barn

Barn is an **artifact-conditioned organization runtime** for long-horizon agent work.

The central rule is intentionally narrow:

> **No specialist without an unresolved work obligation that requires its capability.**

Barn keeps the organization outside the model. Agents may propose work, artifacts, or requests for specialization, but a deterministic transition engine owns what changes are legal, which specialist may exist, whether a compatible specialist should be reused, when evidence is sufficient to close a branch, and when an agent may retire.

## What v0.1 proves

The reference implementation currently demonstrates four behaviors:

1. A work graph can expose an explicit capability gap.
2. That gap can deterministically spawn, reuse, or refuse a specialist under an active-agent budget.
3. Organizational mutations are append-only events with a causal explanation (`Why does this agent exist?`).
4. A specialist branch closes only after a durable artifact and, when required, independent verification; the specialist can then retire.

This is **not** a claim that multi-agent systems outperform a strong single agent. Barn is being built so that claim can eventually be tested under matched budgets.

## Architecture

```text
                       browser / API
                            |
                            v
                     +---------------+
                     | FastAPI Barn  |
                     +-------+-------+
                             |
                    typed commands only
                             |
            +----------------+----------------+
            |                                 |
            v                                 v
   +-------------------+             +------------------+
   | Transition Engine |             | Context Builder  |
   | spawn / reuse     |             | bounded context  |
   | evidence / retire |             +--------+---------+
   +---------+---------+                      |
             |                                v
             |                         +--------------+
             |                         | AgentRuntime |
             |                         +------+-------+
             |                                |
             v                                v
   +-------------------+               Qoder Agent SDK
   | GraphStore        |               (optional)
   | in-memory / Neo4j |
   +-------------------+
```

**Barn owns topology. Qoder owns worker execution.** Qoder's built-in `Agent` subagent tool is deliberately not exposed to Barn workers. Each logical Barn agent receives a stable Qoder session instead.

## Run locally

The base runtime has no required database or model-provider dependency.

```bash
cd barn
PYTHONPATH=src python -m barn
```

Then open `http://127.0.0.1:8000`.

The UI has two deterministic demo steps:

- **Bootstrap demo**: a collaborative-editor goal reveals an unresolved conflict-resolution obligation; Barn licenses one `CRDT Specialist`.
- **Complete specialist branch**: the specialist submits a design artifact, the Chief independently verifies it, the work resolves, and the specialist retires.

Click a crew node to inspect the committed causal path that explains why it exists.

## Tests

```bash
PYTHONPATH=src pytest -q
node --check src/barn/static/app.js
```

The tests exercise event sequencing/idempotency, specialist licensing, evidence gates, causal paths, deterministic readiness, FastAPI behavior, the Neo4j query boundary, bounded runtime context, Qoder session/tool restrictions, MCP tool binding, and the browser demo surface.

## Optional Neo4j integration

Install the optional driver:

```bash
python -m pip install -e '.[neo4j]'
```

Configure:

```bash
export NEO4J_URI='neo4j+s://<instance>.databases.neo4j.io'
export NEO4J_USER='neo4j'
export NEO4J_PASSWORD='...'
export NEO4J_DATABASE='neo4j'
```

`Neo4jGraphStore` keeps a canonical serialized `RunState` plus normalized graph projections for agents, work, dependencies, artifacts, verifications, assignments, spawn provenance, and runtime executions. Execution nodes are linked back to both the logical agent and work item. Cypher structure is fixed in code; model-supplied strings are parameters, not query fragments.

## Optional Qoder integration

Install the Qoder Agent SDK:

```bash
python -m pip install -e '.[qoder]'
```

For a developer workstation, sign in with `qodercli`. `QoderAgentRuntime` reuses that local authentication session by default. A host application can instead inject another authentication factory.

Barn exposes Qoder only a deliberately narrow tool surface:

- `Read`, `Glob`, `Grep`, `Bash`, `Edit`, `Write`
- `mcp__barn__propose_work`
- `mcp__barn__request_specialist`
- `mcp__barn__submit_artifact`
- `mcp__barn__get_context`

The Qoder `Agent` tool and web tools are not in the visible tool set. A Qoder worker therefore cannot create hidden subagents outside Barn's organization graph.

Example host wiring:

```python
from barn.engine import BarnEngine
from barn.qoder_runtime import QoderAgentRuntime
from barn.qoder_tools import make_barn_mcp_server_factory
from barn.runtime import build_context_pack

runtime = QoderAgentRuntime(
    cwd="/path/to/project",
    mcp_server_factory=make_barn_mcp_server_factory(engine),
)

context = await build_context_pack(
    engine.store,
    run_id=run_id,
    agent_id=agent_id,
    work_id=work_id,
    budget={"max_turns": 8},
)
result = await runtime.run(context.agent, context)
```

## Live Qoder + Neo4j probe

Barn includes a fail-closed live integration probe:

```bash
PYTHONPATH=src python scripts/live_qoder_neo4j.py --preflight
```

For an actual run, pass the target repository as the positional argument after preflight succeeds. A live run requires the `qoder-agent-sdk` and `neo4j` Python packages, Qoder authentication (`QODER_PERSONAL_ACCESS_TOKEN` or a usable local Qoder CLI session), and `NEO4J_URI`, `NEO4J_USER`, and `NEO4J_PASSWORD`. When those prerequisites exist, omit `--preflight` to exercise the full path: Qoder worker -> scoped Barn MCP tools -> per-agent Git worktree -> submitted artifact -> Neo4j persistence -> replay audit. The probe verifies exact artifact bytes and SHA-256 rather than trusting the model's completion text.
The preflight report also includes detected `qoder-agent-sdk` and `neo4j` package versions when installed, so a provider-backed evidence record can pin the runtime it actually used.

The current execution container used to build Barn cannot reach PyPI package files and has no Qoder or Neo4j credentials, so a real provider-backed run has not been represented as completed.

## Qoder comparative benchmark

Once Qoder is installed and authenticated, the provider-backed three-policy harness is:

```bash
PYTHONPATH=src python scripts/run_qoder_comparison.py --preflight
PYTHONPATH=src python scripts/run_qoder_comparison.py --max-total-turns 6
```

The experiment compares a single generalist, a pre-staffed architect/builder team, and Barn's artifact-conditioned staffing under one shared total-turn ceiling. Workers must submit their own artifacts through Barn MCP; the host does not synthesize successful artifact records.

## Coding workspaces and orchestration

Each logical agent can receive a deterministic Git worktree/branch owned by Barn. `BarnOrchestrator.execute_work` requires explicit assignment, prepares that workspace, builds a bounded `ContextPack`, materializes only relevant dependency artifacts into `.barn/context/artifacts/` after verifying their committed SHA-256, invokes the configured `AgentRuntime`, and records an `ExecutionRecord`. A successful model turn still leaves the WorkItem unresolved until a real artifact crosses Barn's evidence boundary.

## Replay and audit

Barn's append-only event ledger can reconstruct implemented semantic state from zero with `replay_run(events)`. `GET /runs/{run_id}/audit` independently hashes materialized state and replayed state using a canonical SHA-256 representation and reports whether they match. Persistence `version` is excluded because it is concurrency metadata rather than organization semantics.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for transition, workspace, Qoder, Neo4j, replay, and failure semantics. See [`docs/EXPERIMENTS.md`](docs/EXPERIMENTS.md) for the matched-budget evaluation protocol.

## Core model

### Work lifecycle

```text
proposed -> ready -> active -> review -> resolved
                     |                    ^
                     +---- blocked -------+
```

Resolution requires at least one artifact. If `requires_verification=true`, it also requires a passing verification by an agent other than the artifact producer.

### Agent lifecycle

```text
active <-> idle -> retired
```

Retirement is illegal while unresolved work remains assigned.

### Specialist request

A request contains:

```text
(work_id, required capability, proposed role, reason)
```

Barn checks, in order:

1. requester exists and is not retired;
2. work exists and is not terminal;
3. capability is explicitly required by that work;
4. an existing compatible non-retired agent can be reused;
5. otherwise the active-agent budget permits a new agent.

The outcome is one of `spawned`, `reused`, or `rejected`, and the decision itself is committed as an event.

## Context discipline

A Barn worker does not receive the global conversation or event history by default. `ContextPack` contains only:

- its identity and capabilities;
- target work;
- target ancestors;
- explicit dependency closure;
- artifacts attached to that structural neighborhood;
- current execution budget.

This is meant to make organizational structure serve as durable external memory rather than allowing every worker's prompt to grow with the entire run.

## Current boundaries

Barn v0.1 deliberately does **not** implement:

- learned topology optimization;
- stochastic OSAHR scheduling;
- GraphRAG;
- arbitrary recursive Qoder subagents;
- autonomous production deployment;
- a claim that specialization improves outcomes;
- a claim that an LLM-authored capability requirement is independently true.

That last point matters. In v0.1 an agent may propose a work item and its required capability, but Barn only guarantees that subsequent organization changes are consistent with the committed work graph. A research-grade version should add independent evidence/acceptance rules for capability-gap formation itself.

## OSAHR direction

OSAHR is intentionally **not** on the online execution path yet. The research path is:

1. collect Barn traces;
2. compare single-agent, fixed-team, manager-delegated, and artifact-conditioned policies under matched budgets;
3. estimate failure, latency, cost, rework, and coordination distributions;
4. only then fit an OSAHR Agent-System Twin and evaluate simulated organizational policies against observed runs.

The artifact-conditioned policy earns complexity only if it beats simpler baselines on measured outcomes.

## Repository map

```text
src/barn/domain.py         canonical domain models
src/barn/store.py          GraphStore protocol + in-memory reference store
src/barn/engine.py         deterministic transition engine
src/barn/causal.py         causal explanation queries
src/barn/scheduler.py      derived ready-work frontier
src/barn/neo4j_store.py    optional Neo4j durable store/projection
src/barn/runtime.py        bounded ContextPack + AgentRuntime protocol
src/barn/qoder_runtime.py  optional Qoder worker adapter
src/barn/qoder_tools.py    scoped Barn-owned in-process MCP capability surface
src/barn/workspace.py      deterministic per-agent Git worktrees
src/barn/orchestrator.py   assigned work -> context -> runtime -> execution record
src/barn/replay.py         append-only event reconstruction
src/barn/audit.py          canonical semantic state hash + replay audit
src/barn/metrics.py        descriptive run/execution measurements
src/barn/api.py            FastAPI surface
src/barn/demo.py           deterministic lifecycle demo
src/barn/static/           zero-build browser graph UI
```

The design and task plan that generated this implementation are retained under `docs/superpowers/`.
