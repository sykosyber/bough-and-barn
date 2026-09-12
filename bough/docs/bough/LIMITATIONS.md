# Limitations (v1)

- No adaptation. Non-empty `Rule.adaptation` or mutating `Theta` refuses.
- No meta-rewriting. `R` is constant.
- No time-varying hazards. No thinning window cursor.
- No semi-Markov / delayed completion.
- No decisions racing chance. Decisions are preemptive and instantaneous.
- Non-empty `Z` refuses.
- Residual derived symmetry refuses (`RESIDUAL_SYMMETRY`); no orbit enumeration.
- Neo4j is an **inspection export** (Cypher). It is not the expander. Live push is optional via `NEO4J_URI` and is a no-op without the driver.
- No throughput claim versus SSA. `expand_seconds` vs `refresh_seconds` is a within-Bough measurement. OSAHR's ontology benchmark already showed a correct layer can be slower than Gillespie.
- Rate-on-vertex-attribute edits change `G` (they live on Route vertices) and therefore the situation signature. They are not a same-node parameter refresh.
- `learned` staging is an exact p-vector descriptor. It is not claim C4.
- `causal.py` is trace-only; independence for tests is hand-constructed.
- `reach()` and `optimal_policy` require a DAG. Cyclic automata (the ontology fragment) refuse `CYCLIC_AUTOMATON` rather than summing an infinite series silently. Compression is still reported.
- C2 compares `reach()` to the three kernel schedulers with a Hoeffding alarm. That is a regression bound, not a distributional-equality theorem.
- Truncated expansions label every query as conditional on the horizon.
