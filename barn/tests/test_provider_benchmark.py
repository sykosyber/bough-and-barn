from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from barn.provider_benchmark import run_model_comparison
from barn.runtime import AgentResult


class ArtifactSubmittingRuntime:
    def __init__(self, engine):
        self.engine = engine

    async def run(self, agent, context):
        workspace = Path(context.workspace_path)
        if "Architecture stage" in context.target_work.title:
            path = workspace / "architecture.md"
            path.write_text("Use the smallest deterministic boundary.\n", encoding="utf-8")
            kind = "design"
        else:
            path = workspace / "solution.txt"
            path.write_text("BARN_MODEL_BENCH_OK\n", encoding="utf-8")
            kind = "code"
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        await self.engine.submit_artifact(
            context.run_id,
            agent_id=agent.id,
            work_id=context.target_work.id,
            kind=kind,
            uri=f"file://{path}",
            content_hash=digest,
            command_id=f"fake-artifact-{context.target_work.id}",
        )
        return AgentResult(
            output="artifact submitted",
            session_id=f"fake-{agent.id}",
            total_credits=1.0,
            total_cost_usd=0.01,
            num_turns=1,
        )


@pytest.mark.asyncio
async def test_model_comparison_runs_all_policies_with_runtime_submitted_artifacts(tmp_path):
    report = await run_model_comparison(
        tmp_path,
        runtime_factory=lambda engine, _repo: ArtifactSubmittingRuntime(engine),
        max_total_turns=3,
    )

    assert report.evidence_grade == "provider_backed_if_runtime_is_real"
    assert [item.policy for item in report.results] == ["single", "fixed_team", "barn"]
    assert all(item.passed for item in report.results)
    assert all(item.audit_matches for item in report.results)
    by_policy = {item.policy: item for item in report.results}
    assert by_policy["single"].turns_used == 1
    assert by_policy["fixed_team"].turns_used == 2
    assert by_policy["barn"].turns_used == 2
    assert by_policy["fixed_team"].agent_total == 3
    assert by_policy["barn"].agent_total == 2


def test_qoder_benchmark_preflight_fails_closed_without_sdk():
    from barn.provider_benchmark import check_qoder_benchmark_prerequisites

    result = check_qoder_benchmark_prerequisites(
        environ={},
        module_available=lambda _name: False,
    )

    assert result.ready is False
    assert result.missing == ["python_module:qoder_agent_sdk"]
    assert result.auth_mode is None
