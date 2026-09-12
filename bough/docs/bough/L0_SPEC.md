# L0 source spec (v1)

L0 is a declarative overlay that compiles to OSAHR `Rule` objects plus a `Model`. The kernel validates DPO structure, guards, and hazards. Bough adds one field the kernel does not have: `kind ∈ {chance, decision}`.

## Event

```text
EventSpec:
  id:            str
  kind:          chance | decision
  left:          PatternGraph          # OSAHR
  right:         TemplateGraph         # OSAHR
  guard:         Expr | None          # compiles to osahr.expr, never Python
  hazard:        Expr | None
  conditions:    tuple[GraphCondition, ...]
```

Compile-time refusals (named, never silent):

| Reason | When |
| --- | --- |
| `CHANCE_WITHOUT_HAZARD` | `kind=chance` and `hazard is None` |
| `DECISION_WITH_HAZARD` | `kind=decision` and `hazard` is not the dummy `0` / `0.0` |
| `TIME_VARYING_HAZARD` | `"time"` in `hazard.names` |
| `ADAPTIVE_ASSIGNMENTS` | `Rule.adaptation` non-empty |
| `NON_EMPTY_Z` | `Model.memory` non-empty |
| `META_REWRITING` | `Model.rule_templates` non-empty |

Decision rules are compiled to OSAHR `Rule` objects so the matcher and `RewriteEngine` can run, but they are **never** inserted into an `OccurrenceIndex` or a kernel scheduler. Because OSAHR `Rule.hazard` is a required field, a decision rule is stored with a dummy `Expr("0")` that Bough is forbidden to treat as a real rate. The L0 surface still treats a supplied real hazard on a decision as `DECISION_WITH_HAZARD`.

## Kinds at a situation

At a situation, enumerate matches for both repertoires.

- Only chance occurrences: chance node. Weights `a_i / sum(a)` from evaluated hazards.
- Any decision occurrence: decision node. Chance is suppressed (preemptive, instantaneous). Documented limitation; racing would need semi-Markov clocks, which OSAHR 0.2 excludes.
- Neither: terminal, labeled by the horizon predicate.

`optimal_policy` runs backward induction on the DAG: expectation at chance nodes, max at decision nodes, tie-break `(rule_id, match_id)`. Cyclic automata refuse `CYCLIC_AUTOMATON`.

## Horizon

```text
Horizon:
  max_depth:       int | None
  max_situations:  int           # default 5000
  label:           (state) -> str | None
```

A compilation that stops because `max_situations` was hit is **truncated**. Every inference result must carry `truncated=true` and the horizon. A probability from a truncated expansion is conditional on the cut.

## Abstraction

v1 compiles the embedded jump chain over `(G, B, hash(R))` with `Theta` frozen and `Z` empty. `t` and `n` are decorations, not identity. See `SIGNATURE.md`.
