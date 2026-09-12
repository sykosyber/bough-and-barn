# Bough & Barn — Graph Tools

Two graph tools over one shared substrate, built to be composed.

- **Barn** is the *live* runtime: an artifact-conditioned organization graph for
  long-horizon coding agents. It owns the work graph and crew graph, projects them
  to Neo4j, records empirical execution traces, and licenses every organizational
  mutation (spawn / reuse / retire) through a deterministic transition engine.
- **Bough** is the *offline* compiler: a layer over [OSAHR 0.2](https://github.com/SyberLabs/OSAHR_Cell)
  that expands a typed hypergraph rewrite system into an exhaustively coalesced
  jump-chain with **exact path and reachability probabilities** and a **preemptive
  decision layer** (backward induction), exportable to Neo4j as Cypher.

They meet at a single seam. Barn's spawn/reuse/retire policy is a hand-written
conservative heuristic, and its own architecture explicitly *defers* stochastic /
decision-theoretic OSAHR scheduling to a future phase. Bough is exactly that
deferred layer: it can compile a candidate organizational rewrite system, compute
the exact probability of reaching "run resolved within budget" versus "budget
exhausted", and return the value-optimal action at each situation.

> **Barn owns topology and live execution. Bough owns counterfactual decision
> theory. Both speak Neo4j.** The integration keeps Barn's invariant intact — no
> model call mutates authoritative state — because Bough is a deterministic
> offline compiler whose output is a *suggestion*, never an authorization.

See [`docs/INTEGRATION_PLAN.md`](docs/INTEGRATION_PLAN.md) for the full composed
design, the shared graph model, and the phased build-out.

## Repository layout

```text
barn/     artifact-conditioned organization runtime (FastAPI + in-memory/Neo4j store)
bough/    OSAHR jump-chain compiler (exact probabilities + optimal policy + Cypher export)
docs/     INTEGRATION_PLAN.md and the originating Barn technical implementation plan
```

Each component is a self-contained Python project with its own `pyproject.toml`,
test suite, and docs. They share no import boundary today; the integration described
in `docs/` is a plan, not yet wired code.

## Barn — run it

The base runtime has no required database or model-provider dependency.

```bash
cd barn
PYTHONPATH=src python -m barn          # then open http://127.0.0.1:8000
PYTHONPATH=src pytest -q               # transition/replay/orchestration tests
```

Optional durable store and worker runtime:

```bash
python -m pip install -e '.[neo4j]'    # Neo4jGraphStore projection
python -m pip install -e '.[qoder]'    # QoderAgentRuntime worker adapter
```

Core model: `proposed -> ready -> active -> review -> resolved` for work,
`active <-> idle -> retired` for agents. A specialist branch closes only after a
durable artifact and, when required, independent verification by an agent other
than the producer. Every mutation is an append-only `BarnEvent`; `replay_run`
reconstructs semantic state from zero and `/runs/{id}/audit` hashes materialized
versus replayed state.

## Bough — run it

Needs Python 3.11+ and git (OSAHR is pinned from GitHub).

```bash
cd bough
python -m venv .venv && . .venv/bin/activate      # Windows: .\.venv\Scripts\activate
python -m pip install -e '.[dev]'
python -m pytest -q
python -m bough bits -n 4          # irreversible-bits compression + reach(all-on)
python -m bough ontology --copies 1
python -m bough machine            # hand-solvable protect/ignore MDP -> optimal policy
python -m bough c2                 # reach() vs OSAHR direct_ssa/next_reaction/thinning
python -m bough cypher machine     # Neo4j inspection Cypher (--push if NEO4J_URI set)
```

Headline numbers: bits `n=4` compresses 33 uncoalesced states to 16 (ratio 2.0625)
with `reach(all-on) = 1.0`; the ontology fragment reaches ratio 3.125; the C2 race
`reach(a) = 2/3` agrees with three independent kernel schedulers; the machine MDP
selects **protect** (value 1 vs 0.5). Bough claims *what* is computed, not speed
versus SSA.

## The shared graph

Both tools project into Neo4j with fixed Cypher structure and parameterized values:

- Barn: `(:BarnRun)-[:HAS_AGENT]->(:BarnAgent)`, `(:BarnWork)-[:DEPENDS_ON]->(:BarnWork)`,
  `(:BarnAgent)-[:SPAWNED_BECAUSE]->(:BarnWork)`, `(:BarnArtifact)-[:PRODUCED_FOR]->(:BarnWork)`,
  `(:BarnVerification)-[:VERIFIES]->(:BarnArtifact)`, `(:BarnExecution)-[:EXECUTED_BY]->(:BarnAgent)`.
- Bough: `(:Situation {signature, kind, depth, label, root})-[:JUMP {rule_id, match_id, kind, probability}]->(:Situation)`.

The integration plan defines the bridge that links a Bough `:Situation` to the Barn
run revision and work set it abstracts, turning Barn's "why does this agent exist?"
causal query from *"a capability gap existed"* into *"spawning had expected value V
versus V' for reuse, with exact reach probability p"*.

## Status and honesty boundaries

These are research-grade v0 snapshots, not products, and they are deliberately
restrained about their claims:

- Barn does **not** yet claim that specialization improves outcomes; that requires
  matched-budget experiments against a strong single agent and a fixed team. The one
  committed comparison (`barn/benchmarks/results/`) is a synthetic plumbing smoke
  test and is intentionally *negative* for Barn on inference efficiency.
- Bough does **not** claim speed versus SSA; it claims exact jump-chain probabilities
  and an inspectable coalesced automaton.
- Provider-backed runs (Qoder worker + Neo4j) have **not** been executed: the build
  environment cannot install the SDKs and holds no Qoder or Neo4j credentials. The
  live probes are fail-closed and report this rather than fabricating results.

## Provenance

Both components are SyberLabs work. Bough compiles over OSAHR 0.2; Barn's roadmap
names OSAHR as its long-term simulation and policy layer. This monorepo collects the
two halves and the plan to join them.
