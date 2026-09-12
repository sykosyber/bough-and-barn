from __future__ import annotations

import argparse
import asyncio
import tempfile
from pathlib import Path

from barn.benchmark import run_synthetic_comparison


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Barn's first matched-turn synthetic coordination comparison.")
    parser.add_argument("--max-total-turns", type=int, default=3)
    parser.add_argument("--workdir", type=Path)
    args = parser.parse_args()

    if args.workdir is not None:
        args.workdir.mkdir(parents=True, exist_ok=True)
        report = asyncio.run(run_synthetic_comparison(args.workdir, max_total_turns=args.max_total_turns))
        print(report.model_dump_json(indent=2))
        return 0

    with tempfile.TemporaryDirectory(prefix="barn-comparison-") as tmp:
        report = asyncio.run(run_synthetic_comparison(tmp, max_total_turns=args.max_total_turns))
        print(report.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
