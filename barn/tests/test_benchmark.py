import pytest

from barn.benchmark import run_synthetic_comparison


@pytest.mark.asyncio
async def test_first_comparison_runs_three_policies_under_same_turn_cap(tmp_path):
    report = await run_synthetic_comparison(tmp_path, max_total_turns=3)

    assert report.evidence_grade == "synthetic_smoke_not_model_performance"
    assert [result.policy for result in report.results] == ["single", "fixed_team", "barn"]
    assert all(result.passed for result in report.results)
    assert all(result.turn_budget == 3 for result in report.results)
    assert all(result.turns_used <= result.turn_budget for result in report.results)

    by_policy = {result.policy: result for result in report.results}
    assert by_policy["single"].turns_used == 1
    assert by_policy["single"].agent_total == 1
    assert by_policy["single"].specialists_spawned == 0

    assert by_policy["fixed_team"].turns_used == 2
    assert by_policy["fixed_team"].agent_total == 3
    assert by_policy["fixed_team"].specialists_spawned == 2

    assert by_policy["barn"].turns_used == 2
    assert by_policy["barn"].agent_total == 2
    assert by_policy["barn"].specialists_spawned == 1
    assert all(result.audit_matches for result in report.results)


def test_comparison_summary_does_not_claim_barn_superiority():
    from barn.benchmark import interpret_synthetic_results

    summary = interpret_synthetic_results(
        single_turns=1,
        fixed_turns=2,
        barn_turns=2,
        fixed_agents=3,
        barn_agents=2,
    )

    assert "single-agent baseline is more inference-efficient" in summary
    assert "Barn uses fewer staffed agents than the fixed team" in summary
    assert "not evidence" in summary
