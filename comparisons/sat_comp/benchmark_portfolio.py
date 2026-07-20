#!/usr/bin/env python3
"""Benchmark DIMACS formulas with the paper's three-solver SAT portfolio.

This imports the project evaluator to preserve its timing and race semantics,
but pins the symmetry branch to CaDiCaL 1.9.5.  The current development code
auto-prefers Kissat when present, whereas the paper reports BreakID+CaDiCaL.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path

from pysat.formula import CNF


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent.parent


for variable in (
    "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ[variable] = "1"


def load_portfolio(project: Path, cap: float):
    sat_dir = project / "SAT"
    sys.path.insert(0, str(sat_dir))
    import solution_portfolio as portfolio

    portfolio.require_full_portfolio()
    portfolio._STRONG_CDCL = "cadical195"
    portfolio._BRANCH_TIMEOUT_S = cap
    return portfolio


def to_test(path: Path):
    cnf = CNF(from_file=str(path))
    test = []
    for clause in cnf.clauses:
        test.append({
            "positive": [literal for literal in clause if literal > 0],
            "negative": [-literal for literal in clause if literal < 0],
        })
    return test


def atomic_json(path: Path, value: object) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def git_revision(project: Path) -> str:
    return subprocess.check_output(
        ["git", "-C", str(project), "rev-parse", "HEAD"], text=True
    ).strip()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=HERE / "manifest.csv")
    parser.add_argument("--output", type=Path, default=HERE / "results/screen.json")
    parser.add_argument("--project", type=Path, default=REPOSITORY)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--cap", type=float, default=60.0)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument(
        "--track", action="append", default=[],
        help="keep rows whose comma-separated track list contains this text",
    )
    parser.add_argument(
        "--exclude-family", action="append", default=[],
        help="exclude an exact GBD family label",
    )
    args = parser.parse_args()

    portfolio = load_portfolio(args.project, args.cap)
    rows = list(csv.DictReader(args.manifest.open(encoding="utf-8")))
    if args.track:
        rows = [row for row in rows if any(text in row["tracks"] for text in args.track)]
    if args.exclude_family:
        excluded = set(args.exclude_family)
        rows = [row for row in rows if row["family"] not in excluded]
    if not 0 <= args.shard_index < args.shard_count:
        parser.error("--shard-index must be in [0, --shard-count)")
    rows = [
        row for index, row in enumerate(rows)
        if index % args.shard_count == args.shard_index
    ]
    if args.limit is not None:
        rows = rows[:args.limit]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        report = json.loads(args.output.read_text(encoding="utf-8"))
    else:
        report = {
            "protocol": {
                "portfolio": [
                    "minisat22",
                    "BreakID + cadical195 (flat 0.008 s preprocessing charge)",
                    "CryptoMiniSat via pycryptosat, one thread",
                ],
                "metric": "first finishing branch CPU time, as in SAT/solution_portfolio.py",
                "repeats": args.repeats,
                "aggregation": "median",
                "cap_seconds": args.cap,
                "breakid_runtime_included": False,
            },
            "machine": {
                "platform": platform.platform(),
                "processor": platform.processor(),
                "python": platform.python_version(),
            },
            "project_revision": git_revision(args.project),
            "instances": {},
        }

    done = report["instances"]
    started = time.monotonic()
    for index, row in enumerate(rows, 1):
        key = row["hash"]
        old = done.get(key)
        if old is not None and len(old.get("times", [])) >= args.repeats:
            continue
        local_path = Path(row["local_path"])
        if not local_path.is_absolute():
            local_path = args.manifest.resolve().parent / local_path
        test = to_test(local_path)
        times = list(old.get("times", [])) if old else []
        while len(times) < args.repeats:
            times.append(float(portfolio.solve(test)))
        done[key] = {
            **row,
            "times": times,
            "median": statistics.median(times),
            "min": min(times),
            "max": max(times),
        }
        atomic_json(args.output, report)
        if index % 10 == 0 or index == len(rows):
            elapsed = time.monotonic() - started
            hardest = max(done.values(), key=lambda item: item["median"])
            print(
                f"{index}/{len(rows)} elapsed={elapsed:.1f}s "
                f"hardest={hardest['median']:.6f}s "
                f"{hardest['filename']}",
                flush=True,
            )

    ordered = sorted(done.values(), key=lambda item: item["median"], reverse=True)
    report["ranking"] = [item["hash"] for item in ordered]
    report["completed_at_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    atomic_json(args.output, report)
    print(f"wrote {args.output} with {len(done)} measurements")


if __name__ == "__main__":
    main()
