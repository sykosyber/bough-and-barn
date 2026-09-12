from datetime import datetime, timezone

from barn.domain import (
    Agent,
    AgentStatus,
    BarnEvent,
    ExecutionRecord,
    RunState,
    WorkItem,
    WorkStatus,
)
from barn.metrics import summarize_run


def test_summarize_run_counts_organization_decisions_and_runtime_usage():
    now = datetime.now(timezone.utc)
    state = RunState(
        id="run-metrics",
        goal="Build editor",
        agents={
            "chief": Agent(id="chief", run_id="run-metrics", role="Chief", status=AgentStatus.ACTIVE),
            "worker": Agent(id="worker", run_id="run-metrics", role="CRDT Specialist", status=AgentStatus.RETIRED),
        },
        work_items={
            "root": WorkItem(id="root", run_id="run-metrics", title="Build", status=WorkStatus.ACTIVE),
            "done": WorkItem(id="done", run_id="run-metrics", title="CRDT", status=WorkStatus.RESOLVED),
        },
        executions={
            "exec-1": ExecutionRecord(
                id="exec-1",
                run_id="run-metrics",
                agent_id="worker",
                work_id="done",
                workspace_path="/tmp/work",
                workspace_branch="barn/run/worker",
                runtime_session_id="q1",
                output_summary="done",
                total_cost_usd=0.12,
                total_credits=5,
                num_turns=3,
                started_at=now,
                ended_at=now,
                duration_seconds=1.5,
                created_seq=4,
            ),
            "exec-2": ExecutionRecord(
                id="exec-2",
                run_id="run-metrics",
                agent_id="chief",
                work_id="root",
                workspace_path="/tmp/chief",
                workspace_branch="barn/run/chief",
                output_summary="planning",
                total_cost_usd=None,
                total_credits=2.5,
                num_turns=1,
                started_at=now,
                ended_at=now,
                duration_seconds=2.0,
                created_seq=5,
            ),
        },
    )
    events = [
        BarnEvent(seq=1, run_id=state.id, command_id="s", type="specialist.spawned"),
        BarnEvent(seq=2, run_id=state.id, command_id="r", type="specialist.reused"),
        BarnEvent(seq=3, run_id=state.id, command_id="x", type="specialist.rejected"),
    ]

    metrics = summarize_run(state, events)

    assert metrics.agent_total == 2
    assert metrics.agent_retired == 1
    assert metrics.work_by_status["active"] == 1
    assert metrics.work_by_status["resolved"] == 1
    assert metrics.specialist_spawned == 1
    assert metrics.specialist_reused == 1
    assert metrics.specialist_rejected == 1
    assert metrics.runtime_executions == 2
    assert metrics.runtime_cost_usd_total == 0.12
    assert metrics.runtime_credits_total == 7.5
    assert metrics.runtime_turns_total == 4
    assert metrics.runtime_seconds_total == 3.5
