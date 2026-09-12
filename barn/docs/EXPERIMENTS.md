# Barn Comparative Evaluation

Barn's central empirical question is not whether dynamic agent graphs look useful. It is whether artifact-conditioned specialization improves outcomes relative to simpler coordination under comparable inference budgets.

## Baselines

The first controlled comparison uses three policies over the same task fixture and worker model/runtime:

1. **Strong single agent** — one generalist receives the whole task and may not create specialists.
2. **Fixed specialist team** — a predefined architect/builder/verifier organization exists from the start, regardless of whether every role is needed.
3. **Barn** — begins with one Chief/generalist; specialists may appear only when committed work exposes a required capability that cannot be served by an available compatible agent.

A later experiment may add a fourth **manager-driven dynamic delegation** baseline, but it should not be conflated with the first three-policy comparison.

## Budget matching

For model-backed runs, compare at least:

- same model family/version;
- same task input and repository snapshot;
- same maximum total model turns or credits;
- same wall-clock timeout;
- same external tools;
- same acceptance tests.

If the provider reports credits/tokens/cost, preserve provider measurements in `ExecutionRecord`. Do not infer missing cost data.

## Outcomes

Primary outcomes:

- acceptance-test pass/fail;
- task completion within budget;
- total runtime-reported credits/cost/turns;
- elapsed runtime seconds;
- number of specialists spawned/reused/refused;
- rework count when an artifact fails independent verification.

Secondary structural outcomes:

- maximum simultaneous active agents;
- work graph size/depth;
- unnecessary-agent count for fixed-team policy;
- audit hash match at run end.

## Interpretation discipline

One task is a systems smoke test, not evidence of general superiority. A positive claim about Barn requires repeated tasks, a predefined evaluation set, matched budgets, and reporting of failures as well as successes.

A useful first falsification criterion is straightforward: if Barn is no more reliable than the single agent while consuming materially more inference budget, the dynamic organization mechanism has not earned its complexity on that task class.

## First recorded comparison: synthetic coordination smoke test

The first committed result is `benchmarks/results/2026-09-12-synthetic-comparison.json`. It uses a deterministic scripted worker so it tests Barn's coordination plumbing, worktree isolation, budget accounting, and replay audit rather than model intelligence. All three policies receive the same total-turn cap of 3.

| Policy | Accepted | Turns | Credits | Agents staffed | Specialists spawned | Replay audit |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| Strong single | yes | 1 | 1.0 | 1 | 0 | match |
| Fixed team | yes | 2 | 2.0 | 3 | 2 | match |
| Barn | yes | 2 | 2.0 | 2 | 1 | match |

This result is deliberately negative for Barn on inference efficiency: the single-agent baseline completes the simple fixture in half as many worker turns. Barn only demonstrates organizational parsimony relative to the fixed team by waiting for an explicit implementation capability gap before staffing a builder. This result must not be cited as evidence that Barn improves real model performance.

Reproduce it with:

```bash
PYTHONPATH=src python scripts/run_comparison.py --max-total-turns 3
```

## Live-provider evidence gate

A real comparative claim remains blocked until the same policies run with an actual worker model under matched provider budgets and acceptance tests. The repository contains a Qoder/Neo4j live probe for validating the integration path first. Provider-backed benchmark results should be stored as separate immutable JSON records rather than overwriting the synthetic baseline.

## Qoder-backed comparison harness

`scripts/run_qoder_comparison.py` runs the same three policies with `QoderAgentRuntime`. It does not manufacture artifacts after worker completion: each Qoder worker must create the requested file and call Barn's scoped `submit_artifact` MCP tool. The host verifies that the submitted artifact is inside the worker's Git worktree, that SHA-256 matches committed metadata, and that acceptance bytes match before resolving the work.

Preflight without consuming model turns:

```bash
PYTHONPATH=src python scripts/run_qoder_comparison.py --preflight
```

A provider-backed result is only evidence when the SDK is installed, authentication succeeds, the Qoder model/runtime version is recorded, and the run completes under the shared `--max-total-turns` ceiling. The current build environment cannot execute this run because the Qoder SDK cannot be installed from its network and no Qoder authentication is present.
