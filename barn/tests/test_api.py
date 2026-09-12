from fastapi.testclient import TestClient

from barn.api import create_app


def test_api_creates_run_exposes_snapshot_and_specialist_why_path():
    client = TestClient(create_app())

    created = client.post(
        "/runs",
        json={
            "goal": "Build collaborative editor",
            "max_active_agents": 4,
            "chief_capabilities": ["generalist", "architecture"],
            "command_id": "create",
        },
    )
    assert created.status_code == 201
    run = created.json()
    run_id = run["id"]
    chief_id = next(iter(run["agents"]))
    root_work_id = next(iter(run["work_items"]))

    work_response = client.post(
        f"/runs/{run_id}/work",
        json={
            "actor_agent_id": chief_id,
            "title": "Choose conflict-resolution strategy",
            "description": "Realtime sync needs convergence semantics.",
            "required_capabilities": ["crdt"],
            "parent_work_id": root_work_id,
            "command_id": "work",
        },
    )
    assert work_response.status_code == 201
    work_id = work_response.json()["id"]

    decision_response = client.post(
        f"/runs/{run_id}/specialists/request",
        json={
            "requesting_agent_id": chief_id,
            "work_id": work_id,
            "capability": "crdt",
            "role": "CRDT Specialist",
            "reason": "The work graph exposed unresolved convergence semantics.",
            "command_id": "spawn",
        },
    )
    assert decision_response.status_code == 200
    decision = decision_response.json()
    assert decision["outcome"] == "spawned"

    snapshot = client.get(f"/runs/{run_id}/snapshot")
    assert snapshot.status_code == 200
    assert len(snapshot.json()["state"]["agents"]) == 2

    why = client.get(f"/runs/{run_id}/agents/{decision['agent_id']}/why")
    assert why.status_code == 200
    assert [step["kind"] for step in why.json()["steps"]][-3:] == [
        "capability",
        "request",
        "agent",
    ]


def test_demo_bootstrap_builds_one_specialist_scenario():
    client = TestClient(create_app())
    response = client.post("/demo/bootstrap")
    assert response.status_code == 201
    payload = response.json()
    assert payload["decision"]["outcome"] == "spawned"
    assert len(payload["state"]["agents"]) == 2
    assert payload["specialist_why"]["steps"][-1]["label"] == "CRDT Specialist"


def test_metrics_endpoint_reports_current_run_counts():
    client = TestClient(create_app())
    created = client.post(
        "/runs",
        json={"goal": "Build parser", "chief_capabilities": ["python"], "command_id": "metrics-run"},
    )
    run_id = created.json()["id"]

    response = client.get(f"/runs/{run_id}/metrics")

    assert response.status_code == 200
    metrics = response.json()
    assert metrics["agent_total"] == 1
    assert metrics["work_total"] == 1
    assert metrics["runtime_executions"] == 0
    assert metrics["specialist_spawned"] == 0


def test_assignment_endpoint_assigns_ready_work_to_compatible_agent():
    client = TestClient(create_app())
    created = client.post(
        "/runs",
        json={
            "goal": "Build editor",
            "chief_capabilities": ["generalist", "database"],
            "command_id": "assign-run",
        },
    ).json()
    run_id = created["id"]
    chief_id = next(iter(created["agents"]))
    work = client.post(
        f"/runs/{run_id}/work",
        json={
            "actor_agent_id": chief_id,
            "title": "Design schema",
            "required_capabilities": ["database"],
            "command_id": "assign-work",
        },
    ).json()

    response = client.post(
        f"/runs/{run_id}/work/{work['id']}/assign",
        json={"agent_id": chief_id, "command_id": "assign-chief"},
    )

    assert response.status_code == 200
    assigned = response.json()
    assert assigned["assigned_agent_id"] == chief_id
    assert assigned["status"] == "active"


def test_audit_endpoint_reports_replay_hash_match():
    client = TestClient(create_app())
    created = client.post(
        "/runs",
        json={"goal": "Build parser", "chief_capabilities": ["python"], "command_id": "audit-run"},
    ).json()

    response = client.get(f"/runs/{created['id']}/audit")

    assert response.status_code == 200
    report = response.json()
    assert report["matches"] is True
    assert report["materialized_hash"] == report["replayed_hash"]
    assert report["event_count"] == 1
