from __future__ import annotations

import hashlib
import importlib.util
from importlib.metadata import PackageNotFoundError, version
import os
import shutil
from pathlib import Path
from typing import Callable, Mapping

from pydantic import BaseModel, Field

from .audit import audit_run
from .engine import BarnEngine
from .neo4j_store import Neo4jGraphStore
from .orchestrator import BarnOrchestrator
from .qoder_runtime import QoderAgentRuntime
from .qoder_tools import make_barn_mcp_server_factory
from .workspace import GitWorkspaceManager


class LiveIntegrationUnavailable(RuntimeError):
    pass


class LivePrerequisites(BaseModel):
    ready: bool
    missing: list[str] = Field(default_factory=list)
    qoder_auth_mode: str | None = None
    neo4j_version: str | None = None
    qoder_agent_sdk_version: str | None = None


class LiveIntegrationReport(BaseModel):
    run_id: str
    execution_id: str
    artifact_id: str
    artifact_path: str
    artifact_hash: str
    audit_matches: bool
    qoder_auth_mode: str


def check_live_prerequisites(
    *,
    environ: Mapping[str, str] | None = None,
    module_available: Callable[[str], bool] | None = None,
    executable_available: Callable[[str], bool] | None = None,
    package_version: Callable[[str], str | None] | None = None,
) -> LivePrerequisites:
    env = os.environ if environ is None else environ
    module_available = module_available or (lambda name: importlib.util.find_spec(name) is not None)
    executable_available = executable_available or (lambda name: shutil.which(name) is not None)

    if package_version is None:
        def package_version(name: str) -> str | None:
            try:
                return version(name)
            except PackageNotFoundError:
                return None

    del executable_available  # Published Qoder wheels bundle qodercli; PATH is not authoritative.

    missing: list[str] = []
    neo4j_available = module_available("neo4j")
    qoder_sdk_available = module_available("qoder_agent_sdk")
    if not neo4j_available:
        missing.append("python_module:neo4j")
    if not qoder_sdk_available:
        missing.append("python_module:qoder_agent_sdk")

    if not all(env.get(name) for name in ("NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD")):
        missing.append("neo4j_credentials")

    auth_mode: str | None
    if env.get("QODER_PERSONAL_ACCESS_TOKEN"):
        auth_mode = "pat"
    elif qoder_sdk_available:
        # qodercli_auth() uses the CLI bundled in the platform wheel. Whether a
        # local user is actually signed in is proven by the live query itself.
        auth_mode = "qodercli"
    else:
        auth_mode = None
        missing.append("qoder_auth")

    return LivePrerequisites(
        ready=not missing,
        missing=missing,
        qoder_auth_mode=auth_mode,
        neo4j_version=package_version("neo4j") if neo4j_available else None,
        qoder_agent_sdk_version=(
            package_version("qoder-agent-sdk") if qoder_sdk_available else None
        ),
    )


async def run_live_qoder_neo4j(
    target_repo: str | Path,
    *,
    max_turns: int = 6,
) -> LiveIntegrationReport:
    prerequisites = check_live_prerequisites()
    if not prerequisites.ready or prerequisites.qoder_auth_mode is None:
        raise LiveIntegrationUnavailable(
            "live integration prerequisites missing: " + ", ".join(prerequisites.missing)
        )

    repo = Path(target_repo).resolve()
    store = await Neo4jGraphStore.connect()
    try:
        engine = BarnEngine(store)
        run = await engine.create_run(
            goal=(
                "Create a file named barn_live_probe.txt containing exactly BARN_LIVE_OK followed by a newline. "
                "Compute its SHA-256 and call Barn submit_artifact for this work with kind='probe', the file URI, "
                "and the exact digest. Do not claim completion until the artifact tool succeeds."
            ),
            max_active_agents=2,
            chief_capabilities={"generalist", "python"},
            command_id="live-run",
        )
        chief = next(iter(run.agents.values()))
        root = next(iter(run.work_items.values()))

        auth_factory = None
        if prerequisites.qoder_auth_mode == "pat":
            from qoder_agent_sdk import access_token_from_env

            auth_factory = access_token_from_env

        runtime = QoderAgentRuntime(
            cwd=str(repo),
            max_turns=max_turns,
            mcp_server_factory=make_barn_mcp_server_factory(engine),
            auth_factory=auth_factory,
        )
        orchestrator = BarnOrchestrator(
            engine=engine,
            workspace_manager=GitWorkspaceManager(repo),
            runtime=runtime,
        )
        execution = await orchestrator.execute_work(
            run_id=run.id,
            agent_id=chief.id,
            work_id=root.id,
            command_id="live-execution",
            budget={"max_turns": max_turns},
        )

        final = await store.get_run(run.id)
        artifacts = [artifact for artifact in final.artifacts.values() if artifact.work_id == root.id]
        if len(artifacts) != 1:
            raise LiveIntegrationUnavailable(
                f"Qoder execution did not submit exactly one Barn artifact; observed {len(artifacts)}"
            )
        artifact = artifacts[0]
        artifact_path = _artifact_path(artifact.uri, Path(execution.workspace_path))
        if not artifact_path.exists():
            raise LiveIntegrationUnavailable(f"submitted artifact path does not exist: {artifact_path}")
        digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if digest != artifact.content_hash:
            raise LiveIntegrationUnavailable("submitted artifact hash does not match workspace bytes")
        expected = b"BARN_LIVE_OK\n"
        if artifact_path.read_bytes() != expected:
            raise LiveIntegrationUnavailable("live probe artifact bytes differ from acceptance contract")

        audit = await audit_run(store, run.id)
        if not audit.matches:
            raise LiveIntegrationUnavailable(
                f"Barn replay audit failed after live execution: {audit.replay_error or 'state hash mismatch'}"
            )
        return LiveIntegrationReport(
            run_id=run.id,
            execution_id=execution.id,
            artifact_id=artifact.id,
            artifact_path=str(artifact_path),
            artifact_hash=digest,
            audit_matches=True,
            qoder_auth_mode=prerequisites.qoder_auth_mode,
        )
    finally:
        await store.close()


def _artifact_path(uri: str, workspace: Path) -> Path:
    if uri.startswith("file://"):
        raw = uri[7:]
        candidate = Path(raw)
        return candidate if candidate.is_absolute() else workspace / candidate
    candidate = Path(uri)
    return candidate if candidate.is_absolute() else workspace / candidate
