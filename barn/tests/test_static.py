from fastapi.testclient import TestClient

from barn.api import create_app


def test_root_serves_barn_graph_ui_and_static_assets():
    client = TestClient(create_app())

    root = client.get("/")
    assert root.status_code == 200
    assert "Barn" in root.text
    assert "The work builds the crew" in root.text
    assert '/static/app.js' in root.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "bootstrapDemo" in script.text
    assert "renderCrew" in script.text
    assert "renderWork" in script.text



def test_demo_can_complete_verified_branch_and_retire_specialist():
    client = TestClient(create_app())
    boot = client.post("/demo/bootstrap")
    assert boot.status_code == 201
    payload = boot.json()
    run_id = payload["state"]["id"]
    specialist_id = payload["decision"]["agent_id"]

    completed = client.post(f"/demo/{run_id}/complete")
    assert completed.status_code == 200
    state = completed.json()["state"]

    assert state["agents"][specialist_id]["status"] == "retired"
    conflict_work = next(
        work
        for work in state["work_items"].values()
        if work["title"] == "Choose conflict-resolution strategy"
    )
    assert conflict_work["status"] == "resolved"
    assert len(state["artifacts"]) == 1
    assert len(state["verifications"]) == 1
    verification = next(iter(state["verifications"].values()))
    assert verification["passed"] is True
