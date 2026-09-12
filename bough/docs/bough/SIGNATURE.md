# Situation signature

The signature is the identity of a *situation* in the compiled Markov automaton. It is not the kernel's replay hash.

## What is hashed

```text
sig = BLAKE2b-256( canonical_json( (G_canon, B_canon, repertoire_hash) ) )
```

| Component | In signature? | Notes |
| --- | --- | --- |
| `G` | Yes, after anchored canonicalization | Substantive state. Allocator `next_counter` and `epoch` are **excluded** (they leak discovery order). |
| `B` | Yes | Handle bindings remapped with the same substitution as `G`. |
| `hash(R)` | Yes | Sorted tuple of `rule.hash`. Constant in v0. |
| `Theta` | No | Frozen; path-dependent adaptation is a refusal. |
| `Z` | Excluded; must be empty | Non-empty `Z` → `NON_EMPTY_Z`, not ignored. |
| `t`, `n` | No | Decorations. Depth is recorded on the situation object, not in `sig`. |

Kernel `Hypergraph.state_hash` includes `id_allocator.next_counter` (`graph.py:420-426`). Using it as a situation key would make every create-order unique. Bough therefore serializes vertices and edges only.

Kernel `stable_hash` is SHA-256. Bough uses BLAKE2b so a Bough signature is never accidentally compared as equal to a replay hash. Differential test: states the kernel replay declares identical **must** share a Bough signature. The converse is not asserted.

## Anchored canonicalization

1. **Anchored** entities: every **vertex** ID present in the initial graph `G0`, plus any G0 **edge** that itself carries a `uri` attribute. Vertex IDs are ontology individuals (Site, Route, Person). No relabeling.
2. **Derived** entities: everything else, including mechanism hyperedges (`Available`, `Holds`, …) that are deleted and recreated. Recreated Available edges must remap, or fail→repair is a new situation forever and the compression ratio pins near 1.
3. Colour each entity:
   - anchored: `("A", str(id))`
   - derived vertex: `("V", type_id, canonicalize(attributes))`
   - derived edge: `("E", type_id, canonicalize(attributes))`
4. 1-dimensional Weisfeiler–Lehman refinement over typed incidences. A vertex's neighbours are its incidences `(side, role, ordinal, edge_id)`; an edge's neighbours are `(side, role, ordinal, vertex_id)`. Labels of anchored neighbours stay `("A", str(id))`. Iterate to a fixed point.
5. Sort derived entities by refined colour. **If any colour class of derived entities has size > 1, refuse with `RESIDUAL_SYMMETRY`.** Residual orbits are not enumerated. Instrument the refusal; frequency on real ontologies is a finding.
6. Assign derived IDs `EntityId(namespace=0xB0A7, counter=i)` in that order.
7. Serialize vertices/edges with remapped IDs, then `B` with remapped bindings, then `repertoire_hash`.

Anchored vertices collapse almost all automorphism. That is why a knowledge-graph origin makes this cheaper than full iso-canonical form.

## Validation (tier 1)

- **Confluence.** Two independent events (hand-built disjoint site flips, not `causal.py`). Apply in both orders. Signatures equal.
- **Discrimination.** Two events that change different anchored attributes. Signatures differ.
- **Permutation invariance.** Shuffle rule and match iteration. Situation set identical.
- **Replay differential.** Kernel-identical replay states share a Bough signature. Converse not asserted.

## Why the kernel hash is wrong for coalescence

Replay cares about *this trajectory*: allocator counters, event index, wall-clock-free but order-true IDs. Coalescence cares about the iso class relative to anchored ontology identity. Those are different quotients. Mixing them is the usual way a tree "fails to compress" while remaining probabilistically correct — the silent failure mode in the risk register.
