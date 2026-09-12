# Assumptions verified against OSAHR 0.2.1

Read against `/tmp/OSAHR_Cell` at `59cbe0c` (`osahr` 0.2.1). Each item is the section-20 question from the Bough plan, answered with a file:line reference.

| # | Question | Verdict | Evidence |
| --- | --- | --- | --- |
| 1 | Can `RewriteEngine.apply` be called on a candidate without advancing `Runtime.time`, `n`, or RNG? | **Yes.** | `osahr/rewrite.py:67-96`. `apply` clones graph/boundary/parameters/memory, publishes a `RewriteResult`, and never touches `Runtime`. Time, `event_index`, and `event_id` are caller-supplied. Entity IDs for RHS-only vertices come from `Hypergraph.id_allocator` (`rewrite.py:161-163`), not from `event_index`. |
| 2 | Does `occurrence.py` expose per-match hazards without a scheduler? | **Yes.** | `Occurrence.hazard` (`occurrence.py:32-36`) and `OccurrenceIndex.hazard_at` (`occurrence.py:146-163`) / `_hazard` (`occurrence.py:112-144`). Evaluation is `rule.hazard.evaluate(context)`. Bough v0 also evaluates via `build_expression_context` + `Expr.evaluate` so expansion does not require an `OccurrenceIndex` to be primed by `Runtime`. |
| 3 | Can `Matcher.find_rule_matches` run against an arbitrary graph? | **Yes.** | `osahr/matcher.py:461-484`. Signature is `(graph, rule, *, parameters, memory, time)`. No `Runtime` argument. |
| 4 | Are canonical bindings retrievable per match? | **Yes.** | `Match.bindings` (`matcher.py:30-36`, created at `matcher.py:53-59`). Incremental verification already compares them (`incremental.py:452-454`). |
| 5 | Is `causal.py` queryable statically on a rule pair? | **No. Trace-only.** | `CausalTrace.add` consumes `EventRecord` (`causal.py:80-104`). `EventFootprint.from_record` (`causal.py:35-61`). There is no `independent(rule_a, rule_b)` API. **Confluence tests must use hand-constructed independent pairs** (disjoint site flips; disjoint token attachments), not `causal.py`. |
| 6 | Are incremental dependency signatures accessible as data? | **Yes.** | `RuleDependencySignature.compile(rule)` (`incremental.py:44-71`) is a public `@classmethod`. Fields: `vertex_types`, `vertex_requirements`, `edge_types`, `has_graph_conditions`, `reads_parameters`, `reads_memory`. Sufficient for v0 `derived` staging (phase 5). |
| 7 | Is `float.hex` applied to attributes as well as parameters? | **Yes, for any value that goes through `canonicalize`.** | `canonical.py:67-70`. `Hypergraph.to_canonical` includes `vertex.attributes` / `edge.attributes` (`graph.py:428-455`) and hashing uses `canonical_json` → `float.hex`. Bough signatures must call `canonicalize` on attributes, never `str(float)`. |
| 8 | Do hard limits raise or clamp? | **Raise.** | `ResourceLimitError` (`errors.py:38-39`). `occurrence.py:414-416`, `runtime.py:277-295`, `runtime.py:547`. `invalid_hazard_policy` defaults to `"raise"` (`model.py:31`). Exact modes do not clamp. |

## Housekeeping

- README claims MIT; `LICENSE` in the cloned tree is Apache-2.0-shaped in other metadata historically. Current `pyproject.toml` has `license = "MIT"` and README says MIT. Bough depends on the published terms of OSAHR and does not relicense the kernel.
- Kernel `stable_hash` is **SHA-256** of `canonical_json` (`canonical.py:136-137`), not BLAKE2. BLAKE2 is used in `WeightedIndex` priorities. Bough signatures use **BLAKE2b** over the same `canonical_json` payload, as specified in the plan, so they do not accidentally equal kernel replay hashes (the converse of the differential test must not be asserted).

## Consequences for v0

- Expansion calls `Matcher.find_rule_matches` + `RewriteEngine.is_applicable` + `RewriteEngine.apply` on cloned candidate state. No `Runtime` in the expander.
- Non-empty `Model.memory` or any `Rule.adaptation` is a hard refusal (anti-coalescent `Z` / path-dependent `Theta`).
- Time-dependent hazards (`"time" in rule.hazard.names`) are refused (jump-chain projection).
- `causal.py` is not used in phase 1 tests.
