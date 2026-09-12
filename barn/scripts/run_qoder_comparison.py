from __future__ import annotations

import argparse
import asyncio
import json
import os
import tempfile
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from barn.provider_benchmark import check_qoder_benchmark_prerequisites, run_model_comparison
from barn.qoder_runtime import QoderAgentRuntime
from barn.qoder_tools import make_barn_mcp_server_factory


def _runtime_factory(model: str | None, max_turns: int):
    def factory(engine, repo: Path):
        auth_factory = None
        if os.environ.get("QODER_PERSONAL_ACCESS_TOKEN"):
            from qoder_agent_sdk import access_token_from_env

            auth_factory = access_token_from_env
        return QoderAgentRuntime(
            cwd=str(repo),
            model=model,
            max_turns=max_turns,
            mcp_server_factory=make_barn_mcp_server_factory(engine),
            auth_factory=auth_factory,
        )

    return factory


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Barn's three-policy comparison with Qoder workers.")
    parser.add_argument("--max-total-turns", type=int, default=6)
    parser.add_argument("--model")
    parser.add_argument("--workdir", type=Path)
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()

    prerequisites = check_qoder_benchmark_prerequisites()
    if args.preflight or not prerequisites.ready:
        payload = prerequisites.model_dump(mode="json")
        try:
            payload["qoder_agent_sdk_version"] = version("qoder-agent-sdk")
        except PackageNotFoundError:
            payload["qoder_agent_sdk_version"] = None
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if prerequisites.ready else 2

    runtime_factory = _runtime_factory(args.model, args.max_total_turns)
    evidence_grade = "qoder_provider_backed_model_comparison"
    if args.workdir is not None:
        args.workdir.mkdir(parents=True, exist_ok=True)
        report = asyncio.run(
            run_model_comparison(
                args.workdir,
                runtime_factory=runtime_factory,
                max_total_turns=args.max_total_turns,
                evidence_grade=evidence_grade,
            )
        )
        print(report.model_dump_json(indent=2))
        return 0

    with tempfile.TemporaryDirectory(prefix="barn-qoder-comparison-") as tmp:
        report = asyncio.run(
            run_model_comparison(
                tmp,
                runtime_factory=runtime_factory,
                max_total_turns=args.max_total_turns,
                evidence_grade=evidence_grade,
            )
        )
        print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
