# Bough

Compiler layer over [OSAHR 0.2](https://github.com/SyberLabs/OSAHR_Cell): an exhaustively expanded, coalesced jump-chain over a typed hypergraph rewrite system, with exact path and reachability probabilities and a preemptive decision layer.

This folder is a Bough-only snapshot (no Veil). Intended path on the hackathon machine: `C:\hackathon\bough`.

Bough does **not** claim speed versus SSA. The claim is *what* is computed: exact jump-chain probabilities, an inspectable coalesced automaton, and backward induction.

## Run on Windows (`C:\hackathon\bough`)

```bat
cd C:\hackathon\bough
py -3.12 -m venv .venv
.\.venv\Scripts\activate
python -m pip install -e ".[dev]"
python -m pytest -q
python -m bough bits -n 4
python -m bough ontology --copies 1
python -m bough machine
python -m bough c2
```

Needs Python 3.11+ and git (OSAHR is pinned from GitHub).

## Run on Unix

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python3 -m pytest -q
python3 -m bough bits -n 4
python3 -m bough ontology --copies 1
python3 -m bough machine
python3 -m bough cypher ontology --copies 1
python3 -m bough c2
```

## Headline numbers

Irreversible bits: `n=4` compression **2.0625** (16 situations vs 33 uncoalesced), `reach(all-on) = 1.0` over 24 paths. `n=6` is **3.015625** (64 vs 193).

Ontology fragment (OSAHR 3-site / 3-route fixture, no rdflib): 8 situations, 24 edges, 25 uncoalesced, ratio **3.125**. `copies=2` is 64 situations, ratio **6.015625**. Cyclic; compression is the gate, not `reach()`.

C2 (DAG only): race `reach(a) = 2/3` agrees with `direct_ssa`, `next_reaction`, and `thinning` inside a Hoeffding alarm. Bits-2 absorbs with frequency 1 on every scheduler.

Hand-solvable MDP: `optimal_policy` selects **protect** (value 1 vs 0.5).

## Layout

```
src/bough/           compiler
tests/bough/        tests
docs/bough/         L0 spec, signature, ontology gate, C2, v1 notes
```

Depends on `osahr` 0.2.1 (git pin in `pyproject.toml`). Neo4j is Cypher export only.
