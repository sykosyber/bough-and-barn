from __future__ import annotations

import argparse
import asyncio
import json

from barn.live_integration import (
    LiveIntegrationUnavailable,
    check_live_prerequisites,
    run_live_qoder_neo4j,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the real Qoder -> Barn MCP -> Git worktree -> Neo4j integration probe.")
    parser.add_argument("target_repo", nargs="?", help="Git repository Barn may create an isolated worker worktree from")
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--preflight", action="store_true", help="Only report dependency/auth readiness")
    args = parser.parse_args()

    preflight = check_live_prerequisites()
    if args.preflight:
        print(preflight.model_dump_json(indent=2))
        return 0 if preflight.ready else 2
    if not preflight.ready:
        print(preflight.model_dump_json(indent=2))
        return 2
    if args.target_repo is None:
        parser.error("target_repo is required unless --preflight is used")
    try:
        report = asyncio.run(run_live_qoder_neo4j(args.target_repo, max_turns=args.max_turns))
    except LiveIntegrationUnavailable as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        return 1
    print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
