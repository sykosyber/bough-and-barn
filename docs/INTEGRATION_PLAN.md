# Bough & Barn: Graph Tools — Integration Plan

Status: design plan. No integration code exists in this snapshot; Barn and Bough
are independently installable and share no import boundary yet. This document
defines the seam, the shared graph, the concrete API mapping, and the phased
build-out. It is written to be falsifiable — every phase has an exit criterion
that can fail.

---

## 1. Why these two compose

Barn is an artifact-conditioned organization runtime. Its central rule is narrow
on purpose:

> No specialist without an unresolved work obligation that requires its capability.

Barn keeps the organization *outside* the model. A deterministic transition engine
(`barn.engine.BarnEngine`) owns which mutations are legal, whether a compatible
specialist should be reused, when evidence closes a branch, and when an agent may
retire. The decision today is a **hand-written conservative heuristic**
(`BarnEngine.request_specialist` → `SpecialistDecision` of `SPAWNED` / `REUSED` /
`REJECTED`). Barn's own architecture and roadmap *explicitly defer* the
decision-theoretic version:

> Barn intentionally does not yet include stochastic/OSAHR online scheduling,
> learned topology policies... Those mechanisms are justified only after
> matched-budget experiments establish where simpler baselines fail.
> — `barn/docs/ARCHITECTURE.md`

Bough is precisely that deferred layer. It compiles a typed hypergraph rewrite
system (OSAHR 0.2 `Rule`s tagged `kind ∈ {chance, decision}`) into an exhaustively
expanded, **coalesced** jump-chain (`bough.expand.expand` → `MarkovAutomaton`) with:

- exact reachability probability — `bough.infer.reach(automaton, label) -> (mass, paths)`;
- exact path probability — `bough.infer.path_probability`;
- a value-optimal preemptive policy by backward induction —
  `bough.policy.optimal_policy(automaton, terminal_value) -> Policy`;
- a Neo4j inspection export — `bough.cypher.automaton_to_cypher`.

So the composition is not a mashup of unrelated tools. **Barn is the live graph
that generates organizational traces; Bough is the offline compiler that turns a
candidate organizational process into exact probabilities and an optimal action.**
Both already speak Neo4j. The seam is a projection: Barn `RunState` → Bough model.

The one-line thesis:

> Replace Barn's *heuristic* spawn license with a *measured* one — computed by
> Bough from calibrated rates — while keeping Barn's authority boundary intact.

---

## 2. Invariants that the integration must preserve

These are inherited from Barn and Bough and are non-negotiable. The integration is
only allowed to add a *suggestion*; it may never weaken them.

1. **No model call mutates authoritative state.** Only `BarnEngine` commits. Bough
   is a deterministic offline compiler, not a model, and its output enters Barn as
   advisory provenance — never as a direct mutation.
2. **Suggestion is separate from authorization.** (Barn plan, OSAHR Phase D.) A
   Bough recommendation may inform *which* legal transition to prefer; the engine's
   typed checks (capability required, budget, reuse-before-spawn, verification
   independence) still gate every commit.
3. **The typed boundary holds.** No new path may create/update `Agent`/`WorkItem`
   outside Barn tools and transition validation.
4. **Bough refusals are respected, not bypassed.** `NON_EMPTY_Z`,
   `META_REWRITING`, `ADAPTIVE_ASSIGNMENTS`, `CHANCE_WITHOUT_HAZARD`,
   `DECISION_WITH_HAZARD`, `TIME_VARYING_HAZARD`, and `CYCLIC_AUTOMATON` (from
   `optimal_policy`) are hard stops. The twin is built to satisfy them.
5. **Auditability is unchanged.** `barn.replay.replay_run` must still reconstruct
   semantic state from the ledger, and `GET /runs/{id}/audit` must still report a
   materialized-vs-replayed hash match. Advisory annotations are either derived
   (recomputable) or committed as their own events — never as silent side-writes.
6. **No superiority claim without matched budgets.** Bough-advised staffing earns
   its complexity only if it beats the deterministic baseline under the protocol in
   `barn/docs/EXPERIMENTS.md`.

---

## 3. Composed architecture

```text
                         user / API / UI
                               |
                               v
   +---------------------------------------------------+
   |                     Barn (live)                   |
   |  BarnEngine: propose / request_specialist /        |
   |  submit_artifact / verify / resolve / retire       |
   |  append-only BarnEvent ledger  ->  replay / audit  |
   +------------+---------------------------+-----------+
                |                           |
        typed commits               empirical traces
        (authoritative)             (RunMetrics, ExecutionRecord)
                |                           |
                v                           v
   +------------------------+   +-----------------------------+
   | Neo4j: Barn projection |   | barn_bough bridge (planned) |
   | :BarnRun/:BarnAgent/   |   |  twin.py     RunState -> Model|
   | :BarnWork/:BarnArtifact|   |  calibrate.py metrics->hazard|
   | :BarnVerification/...  |   |  advise.py   expand+policy   |
   +-----------+------------+   |  project.py  automaton->Cypher|
               |                +--------------+--------------+
               |                               |
               |                    compile_model / expand /
               |                    optimal_policy / reach
               |                               v
               |                +------------------------------+
               |                |          Bough (offline)     |
               |                | coalesced MarkovAutomaton    |
               |                | exact reach + optimal Policy |
               |                +--------------+---------------+
               |                               |
               v                               v
   +-------------------------------------------------------+
   |        Neo4j: Bough projection + bridge edges          |
   |  (:Situation)-[:JUMP {rule_id,kind,probability}]->...   |
   |  (:BarnRun)-[:HAS_TWIN]->(:BoughModel)-[:EXPANDS_TO]->  |
   |  (:Situation {root:true})                               |
   |  (:BarnAgent)-[:LICENSED_BY {value,reach}]->(:Situation)|
   +-------------------------------------------------------+
               |
               v
     UI: "Why does this agent exist?" becomes decision-theoretic:
     goal -> unresolved obligation -> capability gap ->
     spawn (value V, reach p) vs reuse (value V') -> agent
```

Barn stays authoritative and online. Bough stays offline and advisory. The bridge
(`barn_bough`, proposed in §8) is the only new component, and it is additive.

---

## 4. The shared Neo4j graph

Both tools already emit fixed-structure Cypher with parameterized model/user
strings. The integration adds a thin bridge layer rather than changing either
projection.

**Barn projection** (`barn/neo4j_store.py`, per `ARCHITECTURE.md`):

```text
(:BarnRun)-[:HAS_AGENT]->(:BarnAgent)
(:BarnRun)-[:HAS_WORK]->(:BarnWork)
(:BarnWork)-[:PARENT_OF]->(:BarnWork)
(:BarnWork)-[:DEPENDS_ON]->(:BarnWork)
(:BarnAgent)-[:ASSIGNED_TO]->(:BarnWork)
(:BarnAgent)-[:SPAWNED_BECAUSE]->(:BarnWork)
(:BarnRun)-[:HAS_ARTIFACT]->(:BarnArtifact)-[:PRODUCED_FOR]->(:BarnWork)
(:BarnRun)-[:HAS_VERIFICATION]->(:BarnVerification)-[:VERIFIES]->(:BarnArtifact)
(:BarnRun)-[:HAS_EXECUTION]->(:BarnExecution)-[:EXECUTED_BY]->(:BarnAgent)
```

**Bough projection** (`bough/cypher.py::automaton_to_cypher`):

```text
CREATE CONSTRAINT situation_signature IF NOT EXISTS
  FOR (s:Situation) REQUIRE s.signature IS UNIQUE;
(:Situation {signature, kind, depth, label, root})
(:Situation)-[:JUMP {rule_id, match_id, kind, probability}]->(:Situation)
```

**Bridge edges (new, additive):**

```text
(:BarnRun)-[:HAS_TWIN]->(:BoughModel {repertoire_hash, horizon, truncated, ratio})
(:BoughModel)-[:EXPANDS_TO]->(:Situation {root:true})
(:Situation)-[:ABSTRACTS]->(:BarnWork)            // which obligations this shape covers
(:BarnAgent)-[:LICENSED_BY {rule_id, value, reach_probability, action}]->(:Situation)
```

`repertoire_hash` is Bough's `spec.repertoire_hash(rules)`; it pins the exact rule
set the twin was compiled from, so an advisory value is reproducible from the
committed twin + horizon. `LICENSED_BY` upgrades Barn's `SPAWNED_BECAUSE` from
"a gap existed" to "spawning had expected value `value` and success reach
`reach_probability` versus the reuse alternative at this situation."

Both projections are inspection surfaces, not sources of truth. Barn's truth is the
event ledger; Bough's truth is the compiled automaton. The bridge never writes back
into Barn semantic state.

---

## 5. Integration surface — concrete API mapping

| Barn (live) | Bough (offline) | Role in the integration |
| --- | --- | --- |
| `domain.RunState` (agents, work_items, artifacts, verifications, executions) | `osahr.Model` graph `G` + `bough.spec.compile_model` | The organizational *shape* becomes the twin's initial hypergraph. |
| `BarnEngine.request_specialist` decision (spawn/reuse/reject) | `EventSpec(kind=DECISION, ...)` rules | Candidate organizational actions become Bough decision rules. |
| worker success/failure, verification pass/fail, rework, blockers | `EventSpec(kind=CHANCE, hazard=...)` rules | Stochastic outcomes become chance rules with calibrated hazards. |
| `metrics.RunMetrics` (`specialist_spawned/reused/rejected`, `runtime_credits_total`, `runtime_seconds_total`, `runtime_turns_total`, `work_by_status`) | hazard `Expr` rates | Empirical distributions calibrate the chance-rule rates. |
| `domain.ExecutionRecord` (per-execution cost/credits/turns/seconds) | per-rule rate + terminal cost weights | Feeds both hazards and the policy's cost penalty. |
| `RunState.max_active_agents`, budget/credits | horizon + terminal `label` predicate | Budget becomes the truncation horizon and the failure label. |
| `causal` "why does this agent exist?" path | `policy.optimal_policy` value + `infer.reach` mass | Causal explanation gains an expected-value and probability annotation. |
| `replay.replay_run` / `audit` canonical hash | `report.CompilationReport` (expand_seconds, ratio, truncated) | Twin compilation is itself reproducible and auditable. |
| `neo4j_store` Barn projection | `cypher.automaton_to_cypher` + `try_push_cypher` | Two projections joined by the bridge edges of §4. |

Bough's public API used by the bridge (from `bough/__init__.py`): `compile_model`,
`expand`, `Horizon`, `optimal_policy`, `reach`, `path_probability`,
`refresh_probabilities`, `automaton_to_cypher`, `report`, `situation_signature`.

---

## 6. Building the Agent-System Twin

The twin is a Bough `BoughModel` whose situations are *organizational shapes*, not
individual run histories. Two Bough constraints drive the projection design.

### 6.1 Abstract away identity and counters, or nothing coalesces

Bough's situation signature is over `(G, B, hash(R))` with `Theta` frozen and `Z`
empty (`docs/bough/SIGNATURE.md`, `L0_SPEC.md`). The ontology family deliberately
omits history counters "so fail→repair can coalesce; they would be order leaks in
`G`" (`bough/families.py::ontology_model`). Barn state is full of order leaks:
`created_seq`, `retired_seq`, `version`, agent ids, `num_turns`. The projection must
**drop them** and keep only decision-relevant features:

- the multiset of unresolved obligations and their required capabilities;
- which capabilities are currently staffed by a non-retired agent;
- the active-agent count versus `max_active_agents`;
- verification gating (which artifacts await independent verification);
- remaining budget as a small discretized counter (bounded, so it cannot leak order).

Two runs that differ only in agent ids or sequencing but present the same coverage
gap must map to the *same* situation. That is the whole point: coalescence is what
makes the jump-chain tractable, and Barn's ids are exactly what would defeat it.

### 6.2 Chance vs decision, and the preemption rule

Bough suppresses chance wherever a decision is enabled (instantaneous preemption;
`L0_SPEC.md`). So the twin must place decisions and chance at *different*
situations:

- **Decision situations** — an unresolved obligation with a capability gap and no
  assigned compatible agent. Enabled rules: `spawn-specialist`, `reuse-agent`,
  `defer-to-generalist`. These are `kind=DECISION` and carry the dummy `Expr("0")`
  hazard Bough requires (a real hazard on a decision is `DECISION_WITH_HAZARD`).
- **Chance situations** — a specialist is executing, or an artifact awaits
  verification. Enabled rules: `worker-succeeds`, `worker-fails`, `verify-passes`,
  `verify-fails`, `rework`, `blocker-appears`. These are `kind=CHANCE` and *must*
  carry a real hazard (`CHANCE_WITHOUT_HAZARD` otherwise).

This mirrors `bough/families.py::machine_model`, the hand-solvable template: two
`DECISION` rules (`protect`, `ignore`) and two `CHANCE` rules (`succeed`, `fail`),
where `optimal_policy` selects `protect` (value 1 vs 0.5). The Barn twin is the same
shape with organizational rules:

```text
# template, expressed in Bough's L0 terms (not committed code)
spawn-specialist   DECISION  gap -> (gap staffed by new agent),            hazard 0
reuse-agent        DECISION  gap -> (gap staffed by existing compatible),  hazard 0
defer-to-generalist DECISION gap -> (gap retained, budget-1),              hazard 0
worker-succeeds    CHANCE    executing -> artifact-submitted,              hazard p_success
worker-fails       CHANCE    executing -> rework (gap reopened),           hazard p_fail
verify-passes      CHANCE    awaiting -> obligation-resolved,             hazard p_verify
verify-fails       CHANCE    awaiting -> rework,                          hazard 1-p_verify
budget-exhausted   CHANCE    any -> terminal(failed) when budget == 0,     hazard ...
```

Terminal labels: `resolved-within-budget` (success), `budget-exhausted`, `failed`.
`terminal_value` assigns e.g. `+1` to success and `0` (or a negative cost) to the
failure labels; `optimal_policy` then returns the value-maximizing action at the
root situation, and `reach(automaton, "resolved-within-budget")` returns the exact
probability of finishing under the chance rules.

### 6.3 Horizon-bounding is mandatory (the CYCLIC_AUTOMATON problem)

Organizational dynamics are naturally cyclic: spawn → work → verify → rework →
spawn. `optimal_policy` runs backward induction on a **DAG** and refuses
`CYCLIC_AUTOMATON`. Therefore the twin used for *policy extraction* must be
expanded with a finite `Horizon(max_depth=..., max_situations=...)` so the automaton
is acyclic. A truncated expansion is honest: Bough requires every inference result
to carry `truncated=true`, and a probability from a truncated expansion is
*conditional on the cut* (`L0_SPEC.md`). The bridge must surface `truncated` in the
`BoughModel` node and never present a truncated value as unconditional.

For genuinely cyclic analysis (steady-state reachability, compression ratio), use
`reach()` and `report()` on the unbounded automaton — not `optimal_policy`. This is
the same split Bough already documents for the cyclic ontology family: "compression
is the gate, not `reach()`".

### 6.4 Calibration

Hazards start as **hand-set priors** (like the ontology fixture's `0.2`/`0.8`
failure/repair) and are replaced by measured rates only when the corpus justifies
it. `metrics.summarize_run` and the `ExecutionRecord` corpus give the raw material:

- `p_success`, `p_fail` per capability/role ← resolved-vs-reopened work counts;
- `p_verify` ← verification pass/fail counts (`verification_count`, rework events);
- cost weights ← `runtime_credits_total`, `runtime_seconds_total`, `runtime_turns_total`.

Barn's own discipline applies: "One task is a systems smoke test, not evidence of
general superiority" (`EXPERIMENTS.md`). A single run does not yield a distribution.
Until N is sufficient, the twin runs on declared priors and says so.

### 6.5 Incrementality

When Barn commits a new event, the twin need not be rebuilt from scratch.
`bough.incrementality.refresh_probabilities` reweights chance edges in place and
refuses `STRUCTURAL_CHANGE` if the `(rule_id, match_id)` set moved;
`structural_rule_hits` tells the bridge whether an edit invalidates the compiled
shape. A spawn that changes coverage changes `G` and therefore the signature — that
is a re-expand, not a refresh. The bridge chooses refresh vs re-expand accordingly.

---

## 7. The decision-feedback loop (suggestion, not authorization)

Today `BarnEngine.request_specialist` resolves reuse-vs-spawn by a fixed order of
checks and returns `REUSED` whenever a compatible non-retired agent exists, else
`SPAWNED` if budget allows, else `REJECTED`. The integration inserts an **advisor**
between "a legal transition exists" and "which legal transition to commit":

1. On a capability gap, build/lookup the twin for the current `RunState`.
2. `expand` within horizon; `optimal_policy` yields the root action and value;
   `reach` yields success probability for that action versus the alternative.
3. Emit a `SpawnAdvice {action, value, reach_probability, truncated, repertoire_hash}`.
4. The engine **still** enforces every hard invariant (capability required, budget,
   reuse-before-spawn, verifier independence). The advisor may only:
   - break ties the heuristic is indifferent about, and
   - annotate the committed decision with value/reach provenance (`LICENSED_BY`).
5. With the advisor disabled, behavior is byte-identical to Barn v0.

This is deliberately weaker than "let Bough decide." It keeps Barn's falsifiable
posture: the heuristic remains the baseline, and the advisor must *demonstrate* an
advantage under matched budgets before it is allowed to change outcomes online.

---

## 8. Proposed bridge module (future, not in this snapshot)

Additive package; depends on `barn` (domain), `bough` (compiler), and `osahr`.
Barn and Bough remain independently installable — nothing here changes their public
surfaces.

```text
barn_bough/
  twin.py        RunState + event ledger -> osahr.Model + bough EventSpec repertoire
                 (abstracts away ids/counters per §6.1; places decision vs chance
                  situations per §6.2; sets Horizon per §6.3)
  calibrate.py   RunMetrics/ExecutionRecord corpus -> hazard Expr rates (§6.4)
  advise.py      expand + optimal_policy + reach -> SpawnAdvice (§7)
  project.py     automaton_to_cypher + bridge edges (§4); optional try_push_cypher
  cli.py         python -m barn_bough advise --run <id>
                 python -m barn_bough project --run <id> [--push]
  tests/         twin fidelity, coalescence ratio, policy cross-check, refusal cases
```

---

## 9. Phased build-out (mapped to Barn's OSAHR roadmap)

Barn's plan already names four OSAHR phases. The integration *is* Phases B–D, with
Bough as the concrete OSAHR-backed tool.

**Phase A — traces (largely done).** Barn records append-only events,
`ExecutionRecord`, and `RunMetrics` with stable semantics.
*Exit:* a run reconstructs exactly via `replay_run` and audits clean. (Barn v0 meets
this today.)

**Phase B — twin projection.** Implement `twin.py` + `calibrate.py`: project a
`RunState` into a compiling `BoughModel` with calibrated hazards.
*Exit:* `compile_model` passes with no refusal on a real Barn fixture; `expand`
within horizon yields a coalesced automaton with ratio > 1; no id/counter leaks into
the situation signature (two id-different, shape-identical runs coalesce).

**Phase C — counterfactual simulation.** Implement `advise.py`: bounded expand →
`optimal_policy` + `reach` for candidate organizations (reuse generalist / add
specialist / add verifier / parallelize two branches).
*Exit:* on a hand-solvable fixture the policy matches a by-hand optimum (the
`machine_model` protect-vs-ignore discipline), and `reach()` agrees with an
independent Monte-Carlo / kernel-scheduler cross-check within a Hoeffding alarm (the
C2 discipline in `bough/compare.py`).

**Phase D — policy experiment (offline-first).** Wire the advisor as suggestion-only
into `request_specialist`; project twins + `LICENSED_BY` into Neo4j; surface value/
reach in the UI causal inspector.
*Exit:* matched-budget comparison of {single agent, fixed team, Barn-heuristic,
Barn-advised} under `barn/docs/EXPERIMENTS.md`. The advisor is promoted to influence
online decisions **only** if it measurably beats the heuristic; otherwise it stays a
provenance/observability annotation and the stronger claim is dropped.

---

## 10. Non-goals / kill list

Inherited from Barn's restraint and Bough's refusals, extended for the seam:

- No vector DB / GraphRAG. The bridge queries exact graph neighborhoods, not
  similar prose.
- No learned spawn policy until traces justify it. Calibration is measurement, not
  a fitted controller.
- No Bough in the authoritative mutation path. Suggestion only (§7).
- No online `optimal_policy` over a cyclic automaton. Horizon-bound for decisions
  (§6.3); respect `CYCLIC_AUTOMATON`.
- No non-empty `Z`, no meta-rewriting, no adaptive parameters in the twin
  (`NON_EMPTY_Z`, `META_REWRITING`, `ADAPTIVE_ASSIGNMENTS`).
- No time-varying hazards (`TIME_VARYING_HAZARD`); rates are vertex attributes.
- No claim that Bough-advised staffing improves outcomes until the matched-budget
  experiment says so.

---

## 11. Risks and open questions

- **State explosion.** Organizational shape space grows with obligations ×
  capabilities × staffed set. Coalescence is the mitigation and the reason Bough
  exists, but horizon bounds are mandatory and truncated results are conditional.
  Open: what is the smallest feature set that preserves decision relevance while
  keeping the automaton small?
- **Abstraction fidelity.** Dropping ids/counters to coalesce could erase a feature
  that actually matters (e.g., per-agent reliability). Open: validate that the
  abstraction preserves outcomes against un-abstracted simulation on fixtures.
- **Calibration scarcity.** Hazards need many runs; one task is a smoke test. Open:
  how much pooling across tasks is legitimate before rates are fiction?
- **Preemption semantics.** Bough suppresses chance at decision situations. Real
  Barn workers execute over time while decisions pend. The twin accepts Bough's
  documented instantaneous-preemption limitation; semi-Markov racing is out of scope
  (OSAHR 0.2 excludes it).
- **Speed.** Bough makes no speed claim versus SSA; a correct overlay "can be
  thousands of times slower than direct simulation." The advisor must be offline /
  cached, never on the hot commit path.

---

## 12. Acceptance criteria for the integration

Mirroring Barn's falsifiable style:

1. **Twin compiles.** A real Barn `RunState` projects to a `BoughModel` that passes
   `compile_model` with no refusal.
2. **It coalesces.** `expand` within horizon reports compression ratio > 1 on a
   non-trivial fixture, and shape-identical/id-different runs share a signature.
3. **Decision provenance is reproducible.** At least one Barn spawn is annotated
   with a Bough `value` and `reach_probability` recomputable from the committed twin
   + `repertoire_hash` + horizon.
4. **Cross-check passes.** `reach()` on the twin agrees with an independent
   Monte-Carlo of the same process within a Hoeffding alarm.
5. **Authority preserved.** Enabling the advisor changes no commit the deterministic
   engine would have rejected; budget and typed-boundary invariants hold; the run
   still audits clean.
6. **Suggestion-only is real.** With the advisor disabled, Barn behavior is
   byte-identical to v0.

If (3)–(4) hold but the matched-budget experiment shows no advantage, the honest
outcome — per Barn's own recommendation — is to keep the graph/provenance
visualization as a useful observability product and discard the stronger
organizational-policy claim.
