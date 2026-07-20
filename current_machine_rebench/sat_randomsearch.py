#!/usr/bin/env python3
"""Checkpointed, serial SAT RandomSearch for the paper portfolios.

Sampling exactly follows Nevergrad RandomSearch's ``parametrization`` sampler:
``parameter.sample()`` after seeding the parameter's RandomState.  Candidate
evaluations time portfolio branches one after another and take their virtual
best CPU-time minimum.  No two solver branches are active simultaneously.
"""

from __future__ import annotations

import argparse
import fcntl
import heapq
import json
import os
import pickle
import platform
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
SAT_DIR = REPOSITORY / "SAT"
sys.path.insert(0, str(REPOSITORY))
sys.path.insert(0, str(SAT_DIR))
from ng_class import My_Test  # noqa: E402
sys.path.pop(0)
sys.path.pop(0)

from sat_common import (  # noqa: E402
    branch_names,
    measure_branch,
    solver_inventory,
    test_to_clauses,
    write_dimacs,
)


for variable in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ[variable] = "1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def atomic_pickle(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(path)


def cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor()


def git_revision() -> str:
    return subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
    ).strip()


def assert_single_cpu() -> list[int]:
    affinity = sorted(os.sched_getaffinity(0))
    if len(affinity) != 1:
        raise SystemExit(
            f"single-core campaign requires one-CPU affinity, got {affinity}; "
            "launch through run_all.sh or taskset -c CPU"
        )
    return affinity


def evaluate(test: list[dict], portfolio: str, repeats: int, cap: float) -> dict:
    clauses, n_vars = test_to_clauses(test)
    branch_runs = {name: [] for name in branch_names(portfolio)}
    portfolio_runs: list[float] = []
    for _ in range(repeats):
        values: list[float] = []
        verdicts: set[str] = set()
        for branch in branch_names(portfolio):
            measured = measure_branch(branch, clauses, n_vars, cap, portfolio=portfolio)
            branch_runs[branch].append(measured)
            values.append(float(measured["charged_cpu_s"]))
            if measured["status"] in ("SAT", "UNSAT"):
                verdicts.add(measured["status"])
        if len(verdicts) > 1:
            raise RuntimeError(f"portfolio branches disagree on SAT status: {verdicts}")
        portfolio_runs.append(min(values))
    return {
        "n_vars": n_vars,
        "n_clauses": len(clauses),
        "portfolio_runs_s": portfolio_runs,
        "score_s": statistics.median(portfolio_runs),
        "branch_runs": branch_runs,
    }


def heap_record(
    heap: list[tuple[float, int, list[int], dict]],
    keep: int,
    score: float,
    index: int,
    encoded: list[int],
    measurement: dict,
) -> None:
    item = (score, index, encoded, measurement)
    if len(heap) < keep:
        heapq.heappush(heap, item)
    elif score > heap[0][0]:
        heapq.heapreplace(heap, item)


def export_top(output_dir: Path, encoding: str, portfolio: str, heap: list) -> list[dict]:
    test_factory = My_Test(1000, 200, encoding=encoding, l=3)
    exported = []
    for rank, (score, index, encoded, measurement) in enumerate(
        sorted(heap, reverse=True), 1
    ):
        test = test_factory.decode_test(encoded)
        clauses, n_vars = test_to_clauses(test)
        filename = f"{portfolio}_{encoding}_rank{rank:02d}_eval{index:06d}.cnf"
        path = output_dir / "candidates" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        write_dimacs(path, clauses, n_vars)
        exported.append(
            {
                "rank_by_selection_score": rank,
                "evaluation_index": index,
                "selection_score_s": score,
                "selection_measurement": measurement,
                "file": str(path),
                "n_vars": n_vars,
                "n_clauses": len(clauses),
            }
        )
    return exported


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--portfolio", choices=("original3", "dpll4"), required=True)
    parser.add_argument("--encoding", choices=("kcnf", "mprefix"), required=True)
    parser.add_argument("--budget", type=int, default=100_000)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seed", type=int, default=20_260_601)
    parser.add_argument("--cap", type=float, default=60.0)
    parser.add_argument("--keep", type=int, default=20)
    parser.add_argument("--checkpoint-every", type=int, default=100)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.budget <= 0 or args.repeats <= 0 or args.keep <= 0:
        parser.error("budget, repeats, and keep must be positive")

    affinity = assert_single_cpu()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.portfolio}_{args.encoding}"
    state_path = output_dir / f"{stem}.state.pkl"
    report_path = output_dir / f"{stem}.json"
    lock_path = output_dir / f"{stem}.lock"
    lock_handle = lock_path.open("a+", encoding="utf-8")
    try:
        fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"waiting for active {stem} screen at {lock_path}", flush=True)
        fcntl.flock(lock_handle, fcntl.LOCK_EX)

    factory = My_Test(1000, 200, encoding=args.encoding, l=3)
    parameter = factory.encode()
    parameter.random_state.seed(args.seed)
    heap: list[tuple[float, int, list[int], dict]] = []
    completed = 0
    started_at = utc_now()
    if state_path.exists():
        with state_path.open("rb") as handle:
            state = pickle.load(handle)
        expected = {
            "portfolio": args.portfolio,
            "encoding": args.encoding,
            "budget": args.budget,
            "repeats": args.repeats,
            "seed": args.seed,
            "cap": args.cap,
            "keep": args.keep,
        }
        if state["protocol"] != expected:
            raise SystemExit(f"checkpoint protocol mismatch in {state_path}")
        parameter.random_state.set_state(state["random_state"])
        heap = state["heap"]
        completed = state["completed"]
        started_at = state["started_at"]

    protocol = {
        "portfolio": args.portfolio,
        "encoding": args.encoding,
        "budget": args.budget,
        "repeats": args.repeats,
        "seed": args.seed,
        "cap": args.cap,
        "keep": args.keep,
    }
    start = time.monotonic()
    for index in range(completed, args.budget):
        encoded_array = parameter.sample().value
        encoded = [int(value) for value in encoded_array]
        test = factory.decode_test(encoded)
        measurement = evaluate(test, args.portfolio, args.repeats, args.cap)
        score = float(measurement["score_s"])
        heap_record(heap, args.keep, score, index, encoded, measurement)
        completed = index + 1
        if completed % args.checkpoint_every == 0 or completed == args.budget:
            state = {
                "protocol": protocol,
                "completed": completed,
                "random_state": parameter.random_state.get_state(),
                "heap": heap,
                "started_at": started_at,
            }
            atomic_pickle(state_path, state)
            best = max(heap, key=lambda item: item[0])
            print(
                f"{stem}: {completed}/{args.budget} "
                f"best={best[0]:.6f}s at eval {best[1]} "
                f"elapsed={time.monotonic() - start:.1f}s",
                flush=True,
            )

    exported = export_top(output_dir, args.encoding, args.portfolio, heap)
    report = {
        "schema_version": 1,
        "protocol": protocol,
        "started_at": started_at,
        "completed_at": utc_now(),
        "project_revision": git_revision(),
        "machine": {
            "hostname": platform.node(),
            "cpu_model": cpu_model(),
            "platform": platform.platform(),
            "python": sys.version,
            "cpu_affinity": affinity,
        },
        "solver_inventory": solver_inventory(),
        "candidates": exported,
    }
    atomic_json(report_path, report)
    print(f"wrote {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
