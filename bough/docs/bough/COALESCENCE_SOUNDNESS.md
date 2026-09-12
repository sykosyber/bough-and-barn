# Coalescence soundness (occurrence counting)

## Counting convention in force

OSAHR 0.2 **excludes automorphism-orbit occurrence counting** (ARCHITECTURE.md section 20). Occurrences are **per injective match**. A situation with a non-trivial automorphism group therefore contributes `|Aut|` times as many channels, for a given orbit of embeddings, as an orbit-counting semantics would.

Bough inherits this convention. Branch probabilities on a chance node are

```text
p(o | s) = a(o) / sum_{o' enabled at s} a(o')
```

where `o` ranges over DPO-applicable matches, not orbits. Absolute rates (CTMC holding times) differ from orbit-counting semantics by a factor of the relevant automorphism-group orders. The **embedded jump chain** over iso classes is still well-defined, because:

1. DPO rewriting is functorial on graph homomorphisms, hence on isomorphisms.
2. The set of injective matches out of `G` is an invariant of the iso class of `G`.
3. After anchored quotient (individualizing the initial ontology entities), `Aut` is trivial on every situation that v0 accepts. Residual non-trivial colour classes are **refused** (`RESIDUAL_SYMMETRY`), so v0 never silently drops an automorphism factor.
4. Therefore, in every automaton Bough v0 actually emits, per-match counting and orbit counting coincide.

## What coalescence identifies

Two concrete states `X`, `X'` coalesce iff `signature(X) = signature(X')`. The signature is the anchored iso class of `(G, B)` plus `hash(R)` (`SIGNATURE.md`). It is not kernel replay identity.

The expander's signature-keyed dedup **is** coalescence. There is no second pass.

Parallel edges (two matches of the same or different rules reaching the same successor class) are stored separately and their jump probabilities **add**. This is the main compression of path measure onto the automaton.

## Soundness sketch for the jump chain

Let `[[G]]` be the anchored iso class of `G`.

- Enabled match multiset of `G` is a class invariant under the anchored labelling (anchored IDs are part of the class).
- `RewriteEngine.apply` on a match yields a concrete `G'`. `signature(G')` depends only on `[[G']]`.
- The multiset of successor classes, weighted by `a(o)`, is therefore a function of `[[G]]`.
- The embedded discrete-time jump chain on situations is the Markov chain with those normalized weights.
- Continuous time (`t`) is a decoration: holding times are `Exp(sum a)` at chance nodes and are not needed for jump-chain path probability.

This argument does **not** license compiling a model with non-empty `Z`, adaptive `Theta`, or time-varying hazards. Those make the jump chain on `[[G]]` non-Markovian. They refuse.

## Uncoalesced reference

The coalesced automaton is never its own oracle. The uncoalesced tree (every edge creates a fresh node) is the reference object, exactly as `Matcher` is the reference for `IndexedMatcher`. Compression ratio is

```text
ratio = uncoalesced_node_count / situation_count
```

where `uncoalesced_node_count` starts at 1 and increments on every edge creation, including parallel edges. Ratio `1.0` after excluding order-dependent leaks (`epoch`, `n`, allocator) is a phase-2 stop.

## What this document does not claim

- It does not claim orbit-counting CTMC rates.
- It does not claim that residual symmetry is rare; v0 refuses it so the claim is unnecessary.
- It does not claim faster than SSA.
