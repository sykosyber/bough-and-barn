from barn.live_integration import LivePrerequisites, check_live_prerequisites


def test_live_preflight_reports_missing_sdk_database_and_auth():
    result = check_live_prerequisites(
        environ={},
        module_available=lambda _name: False,
        executable_available=lambda _name: False,
    )

    assert result.ready is False
    assert set(result.missing) == {
        "python_module:neo4j",
        "python_module:qoder_agent_sdk",
        "neo4j_credentials",
        "qoder_auth",
    }


def test_live_preflight_accepts_pat_and_neo4j_credentials():
    env = {
        "NEO4J_URI": "neo4j+s://example",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "secret",
        "QODER_PERSONAL_ACCESS_TOKEN": "token",
    }
    result = check_live_prerequisites(
        environ=env,
        module_available=lambda _name: True,
        executable_available=lambda _name: False,
    )

    assert isinstance(result, LivePrerequisites)
    assert result.ready is True
    assert result.missing == []
    assert result.qoder_auth_mode == "pat"


def test_live_preflight_accepts_bundled_qodercli_login_path():
    env = {
        "NEO4J_URI": "neo4j+s://example",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "secret",
    }
    result = check_live_prerequisites(
        environ=env,
        module_available=lambda _name: True,
        executable_available=lambda _name: False,
    )

    assert result.ready is True
    assert result.qoder_auth_mode == "qodercli"


def test_live_preflight_reports_provider_versions_when_available():
    env = {
        "NEO4J_URI": "neo4j+s://example",
        "NEO4J_USER": "neo4j",
        "NEO4J_PASSWORD": "secret",
        "QODER_PERSONAL_ACCESS_TOKEN": "token",
    }
    versions = {"neo4j": "6.2.0", "qoder-agent-sdk": "1.0.14"}

    result = check_live_prerequisites(
        environ=env,
        module_available=lambda _name: True,
        executable_available=lambda _name: False,
        package_version=lambda name: versions.get(name),
    )

    assert result.neo4j_version == "6.2.0"
    assert result.qoder_agent_sdk_version == "1.0.14"


def test_live_preflight_cli_does_not_require_target_repo():
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    for key in ("QODER_PERSONAL_ACCESS_TOKEN", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, str(repo / "scripts" / "live_qoder_neo4j.py"), "--preflight"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ready"] is False
    assert "neo4j_credentials" in payload["missing"]


def test_live_preflight_cli_does_not_require_target_repo():
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(repo / "src")
    for key in ("QODER_PERSONAL_ACCESS_TOKEN", "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD"):
        env.pop(key, None)

    result = subprocess.run(
        [sys.executable, str(repo / "scripts" / "live_qoder_neo4j.py"), "--preflight"],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ready"] is False
    assert "neo4j_credentials" in payload["missing"]
