# Phase 2: ontology-fragment ratio

Gate from the plan: compile OSAHR's 3-site / 3-route fragment, expand, report compression. If the ratio is ~1.0 after excluding order leaks, stop.

## Fragment

Hardcoded from `benchmarks/ontology/routes.ttl` in OSAHR. No rdflib dependency.

| Route | Initial | λ (fail) | μ (repair) |
| --- | --- | --- | --- |
| AB | up | 0.2 | 0.8 |
| AC | up | 0.1 | 0.4 |
| BC | down | 0.5 | 0.5 |

Sites and Routes are URI-identified vertices. Availability is an `Available` hyperedge: **deleted** on fail, **recreated** on repair. Failure/repair counters from a tracing kernel are omitted; they would be `n`-like order leaks in `G`.

## Anchoring

G0 **vertices** stay anchored. Mechanism edges do not. Fail→repair of AB returns to the start signature. Anchoring G0 edge IDs makes that pair diverge (regression test).

## Headline numbers

Independent binary routes. The jump chain is the 3-bit hypercube with a reverse edge on every bit: 8 situations, 24 edges, 25 uncoalesced nodes, ratio **3.125**.

`copies=2` is six independent routes: 64 situations, 384 edges, 385 uncoalesced, ratio **6.015625**. Ratio grows with instance size (C1 on this family).

The automaton is cyclic (relapse). `reach()` refuses `CYCLIC_AUTOMATON`. The gate is compression, not absorption mass.

Derived staging pools by enabled rule-id set: `{fail}`, `{repair}`, `{fail,repair}` → **3** stages vs 8 situations.

## Stop / go

Ratio 3.125 is not ~1.0. Phase 2 passes. Continue v1 (decisions, staging, incrementality, Neo4j inspection). Do not advertise speed versus SSA.
