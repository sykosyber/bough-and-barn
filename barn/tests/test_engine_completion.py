import pytest

from barn.engine import BarnEngine, TransitionError
from barn.store import InMemoryGraphStore


async def _specialist_case(*, requires_verification: bool = False):
    engine = BarnEngine(InMemoryGraphStore())
    run = await engine.create_run(
        goal="Build editor",
        max_active_agents=4,
        chief_capabilities={"generalist"},
        command_id="create",
    )
    chief = next(iter(run.agents.values()))
    work = await engine.add_work(
        run.id,
        actor_agent_id=chief.id,
        title="Define convergence",
        required_capabilities={"crdt"},
        requires_verification=requires_verification,
        command_id="work",
    )
    decision = await engine.request_specialist(
        run.id,
        requesting_agent_id=chief.id,
        work_id=work.id,
        capability="crdt",
        role="CRDT Specialist",
        reason="Convergence is unresolved.",
        command_id="spawn",
    )
    return engine, run.id, chief.id, decision.agent_id, work.id


async def test_work_cannot_resolve_without_artifact():
    engine, run_id, _chief_id, specialist_id, work_id = await _specialist_case()

    with pytest.raises(TransitionError, match="artifact_required"):
        await engine.resolve_work(
            run_id,
            actor_agent_id=specialist_id,
            work_id=work_id,
            command_id="resolve",
        )


async def test_verified_work_requires_passing_independent_verification():
    engine, run_id, chief_id, specialist_id, work_id = await _specialist_case(
        requires_verification=True
    )
    artifact = await engine.submit_artifact(
        run_id,
        agent_id=specialist_id,
        work_id=work_id,
        kind="design",
        uri="artifact://crdt-design",
        content_hash="abc123",
        command_id="artifact",
    )

    with pytest.raises(TransitionError, match="passing_verification_required"):
        await engine.resolve_work(
            run_id,
            actor_agent_id=specialist_id,
            work_id=work_id,
            command_id="resolve-before-verification",
        )

    with pytest.raises(TransitionError, match="independent_verifier_required"):
        await engine.record_verification(
            run_id,
            verifier_agent_id=specialist_id,
            artifact_id=artifact.id,
            passed=True,
            evidence="Self-review says good.",
            command_id="self-verify",
        )

    await engine.record_verification(
        run_id,
        verifier_agent_id=chief_id,
        artifact_id=artifact.id,
        passed=True,
        evidence="Chief checked invariants and examples.",
        command_id="verify",
    )
    resolved = await engine.resolve_work(
        run_id,
        actor_agent_id=specialist_id,
        work_id=work_id,
        command_id="resolve-after-verification",
    )

    assert resolved.status.value == "resolved"


async def test_specialist_cannot_retire_with_unresolved_assigned_work():
    engine, run_id, _chief_id, specialist_id, work_id = await _specialist_case()

    with pytest.raises(TransitionError, match="unresolved_work_assigned"):
        await engine.retire_agent(run_id, agent_id=specialist_id, command_id="retire-too-soon")

    await engine.submit_artifact(
        run_id,
        agent_id=specialist_id,
        work_id=work_id,
        kind="design",
        uri="artifact://design",
        content_hash="hash",
        command_id="artifact",
    )
    await engine.resolve_work(
        run_id,
        actor_agent_id=specialist_id,
        work_id=work_id,
        command_id="resolve",
    )
    retired = await engine.retire_agent(
        run_id, agent_id=specialist_id, command_id="retire-after-completion"
    )

    assert retired.status.value == "retired"
