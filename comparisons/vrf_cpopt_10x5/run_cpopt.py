#!/usr/bin/env python3
"""Serial CP Optimizer comparison under the paper's 10x5 NPFS model.

The processing-time matrices are our champion and the ten public
Vallada--Ruiz--Framinan (VRF) 10x5 matrices.  VRF introduced its matrices for
permutation flow shop; this script deliberately re-solves them as
non-permutation flow shop ``F_m || C_max`` using independent machine orders.

The primary statistic is the geometric mean of child-process CPU time over
CP Optimizer RandomSeed 1..10.  Runs are deliberately serial and use one
worker.  Solver status and objective are recorded so a cap cannot silently be
treated as a completed timing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import docplex
from docplex.cp.model import CpoModel
import docplex.cp.config as cpconfig


HERE = Path(__file__).resolve().parent
DEFAULT_INSTANCES = HERE / "instances.json"
DEFAULT_SEEDS = tuple(range(1, 11))
KNOWN_CPOPT_PATHS = (
    # site-specific install paths removed for anonymization; set
    # CPOPT_EXECFILE or have cpoptimizer on PATH
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_output(*args: str) -> str | None:
    try:
        return subprocess.check_output(
            ["git", *args], cwd=HERE, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def cpu_model() -> str | None:
    path = Path("/proc/cpuinfo")
    if not path.exists():
        return platform.processor() or None
    for line in path.read_text().splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor() or None


def find_cpoptimizer() -> str:
    candidates = [os.environ.get("CPOPT_EXECFILE"), shutil.which("cpoptimizer")]
    candidates.extend(KNOWN_CPOPT_PATHS)
    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return os.path.realpath(candidate)
    raise SystemExit(
        "cpoptimizer not found; set CPOPT_EXECFILE or activate an environment "
        "containing the IBM CP Optimizer executable"
    )


def parse_seeds(value: str) -> tuple[int, ...]:
    seeds: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            seeds.extend(range(lo, hi + 1))
        else:
            seeds.append(int(part))
    result = tuple(dict.fromkeys(seeds))
    if not result or any(seed < 0 for seed in result):
        raise argparse.ArgumentTypeError("seeds must be nonnegative, e.g. 1-10")
    return result


def load_instances(path: Path, selected: tuple[str, ...]) -> list[dict]:
    payload = json.loads(path.read_text())
    if payload.get("problem") != "permutation_flow_shop_makespan":
        raise SystemExit(f"unexpected problem in {path}")
    n = int(payload["n_jobs"])
    m = int(payload["n_machines"])
    all_instances = payload["instances"]
    ids = [instance["id"] for instance in all_instances]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate instance id")
    wanted = set(selected or ids)
    unknown = wanted - set(ids)
    if unknown:
        raise SystemExit(f"unknown instance id(s): {sorted(unknown)}")
    result = []
    for instance in all_instances:
        if instance["id"] not in wanted:
            continue
        matrix = instance["matrix"]
        if len(matrix) != n or any(len(row) != m for row in matrix):
            raise SystemExit(f"bad shape for {instance['id']}; expected {n}x{m}")
        if any(not isinstance(x, int) or not 1 <= x <= 100 for row in matrix for x in row):
            raise SystemExit(f"bad processing time in {instance['id']}")
        result.append(instance)
    return result


def child_cpu_time() -> float:
    usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return usage.ru_utime + usage.ru_stime


def solve(matrix: list[list[int]], seed: int, time_limit: float) -> dict:
    n = len(matrix)
    m = len(matrix[0])
    model = CpoModel()
    operations = {
        (i, j): model.interval_var(size=int(matrix[i][j]), name=f"O_{i}_{j}")
        for i in range(n)
        for j in range(m)
    }
    for i in range(n):
        for j in range(m - 1):
            model.add(model.end_before_start(operations[i, j], operations[i, j + 1]))
    for j in range(m):
        model.add(model.no_overlap([operations[i, j] for i in range(n)]))
    model.minimize(model.max(model.end_of(operations[i, m - 1]) for i in range(n)))

    cpu_start = child_cpu_time()
    wall_start = time.perf_counter()
    result = model.solve(
        Workers=1,
        RandomSeed=int(seed),
        TimeLimit=float(time_limit),
        LogVerbosity="Quiet",
    )
    wall_time = time.perf_counter() - wall_start
    cpu_time = child_cpu_time() - cpu_start
    if result is None:
        return {
            "status": "NoResult",
            "cpu_time_s": cpu_time,
            "wall_time_s": wall_time,
            "objective_values": [],
            "objective_bounds": [],
        }
    infos = result.get_solver_infos() or {}
    keep_info = (
        "NumberOfBranches",
        "NumberOfChoicePoints",
        "NumberOfFails",
        "NumberOfSolutions",
        "PeakMemoryUsage",
        "SearchStatus",
        "SearchStopCause",
        "SolveTime",
    )
    return {
        "status": str(result.get_solve_status()),
        "cpu_time_s": cpu_time,
        "wall_time_s": wall_time,
        "solver_solve_time_s": result.get_solve_time(),
        "objective_values": list(result.get_objective_values() or ()),
        "objective_bounds": list(result.get_objective_bounds() or ()),
        "solver_info": {key: infos[key] for key in keep_info if key in infos},
    }


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def run_is_proven(run: dict | None) -> bool:
    if run is None or run.get("status") != "Optimal":
        return False
    objectives = run.get("objective_values") or []
    bounds = run.get("objective_bounds") or []
    return bool(objectives) and objectives == bounds


def summarize(payload: dict) -> dict:
    seeds = payload["protocol"]["seeds"]
    selected_ids = payload["protocol"]["instance_ids"]
    by_key = {(run["instance_id"], run["seed"]): run for run in payload["runs"]}
    instances = {}
    for instance_id in selected_ids:
        runs = [by_key.get((instance_id, seed)) for seed in seeds]
        complete = all(run_is_proven(run) for run in runs)
        entry = {
            "complete_and_optimal": complete,
            "statuses": [None if run is None else run["status"] for run in runs],
            "objective_matches_bound": [
                None if run is None else run_is_proven(run) for run in runs
            ],
        }
        if complete:
            times = [float(run["cpu_time_s"]) for run in runs]
            entry.update(
                {
                    "times_s_seed_order": times,
                    "geomean_s": statistics.geometric_mean(times),
                    "median_s": statistics.median(times),
                    "min_s": min(times),
                    "max_s": max(times),
                    "max_over_min": max(times) / min(times),
                }
            )
        instances[instance_id] = entry
    summary = {"instances": instances}
    vrf = {
        key: value
        for key, value in instances.items()
        if key.startswith("VFR") and value["complete_and_optimal"]
    }
    ours = instances.get("ours_81f8_DE_7505")
    if vrf and ours and ours["complete_and_optimal"]:
        hardest_id, hardest = max(vrf.items(), key=lambda item: item[1]["geomean_s"])
        summary["comparison"] = {
            "hardest_vrf_id": hardest_id,
            "hardest_vrf_geomean_s": hardest["geomean_s"],
            "our_geomean_s": ours["geomean_s"],
            "ratio_our_over_hardest_vrf_geomean": (
                ours["geomean_s"] / hardest["geomean_s"]
            ),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instances-file", type=Path, default=DEFAULT_INSTANCES)
    parser.add_argument("--instance", action="append", default=[], dest="selected")
    parser.add_argument("--seeds", type=parse_seeds, default=DEFAULT_SEEDS)
    parser.add_argument("--time-limit", type=float, default=600.0)
    parser.add_argument("--expect-cpu", help="required substring of /proc/cpuinfo model name")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    instances_path = args.instances_file.resolve()
    instances = load_instances(instances_path, tuple(args.selected))
    model_name = cpu_model()
    if args.expect_cpu and args.expect_cpu.lower() not in (model_name or "").lower():
        raise SystemExit(f"wrong machine: expected CPU containing {args.expect_cpu!r}, got {model_name!r}")

    cpoptimizer = find_cpoptimizer()
    cpconfig.context.solver.local.execfile = cpoptimizer
    cpconfig.context.solver.local.process_start_timeout = 60
    protocol = {
        "evaluation_problem": "non-permutation flow shop F_m||C_max",
        "source_suite_problem": "permutation flow shop makespan",
        "instance_file_sha256": sha256(instances_path),
        "instance_ids": [instance["id"] for instance in instances],
        "seeds": list(args.seeds),
        "time_limit_s": args.time_limit,
        "workers": 1,
        "timing": "RUSAGE_CHILDREN user+system CPU delta",
        "run_order": "seed-major, then instances.json order",
    }
    output = args.output.resolve()
    if output.exists():
        payload = json.loads(output.read_text())
        if payload.get("protocol") != protocol:
            raise SystemExit("existing output has a different protocol; choose another output path")
        payload.setdefault("resumed_at", []).append(utc_now())
    else:
        payload = {
            "schema_version": 1,
            "created_at": utc_now(),
            "protocol": protocol,
            "machine": {
                "hostname": platform.node(),
                "cpu_model": model_name,
                "platform": platform.platform(),
                "python": sys.version,
                "python_executable": sys.executable,
                "docplex_version": getattr(docplex, "__version__", None),
                "cpoptimizer_path": cpoptimizer,
                "cpoptimizer_sha256": sha256(Path(cpoptimizer)),
                "cpu_affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else None,
                "load_average_at_start": list(os.getloadavg()) if hasattr(os, "getloadavg") else None,
            },
            "repository": {
                "commit": git_output("rev-parse", "HEAD"),
                "branch": git_output("branch", "--show-current"),
                "status_porcelain_at_start": git_output("status", "--porcelain"),
            },
            "runs": [],
        }
    completed = {(run["instance_id"], run["seed"]) for run in payload["runs"]}
    for seed in args.seeds:
        for instance in instances:
            key = (instance["id"], seed)
            if key in completed:
                print(f"skip checkpointed {instance['id']} seed {seed}", flush=True)
                continue
            measured = solve(instance["matrix"], seed, args.time_limit)
            record = {
                "instance_id": instance["id"],
                "seed": seed,
                "finished_at": utc_now(),
                **measured,
            }
            payload["runs"].append(record)
            payload["summary"] = summarize(payload)
            atomic_write(output, payload)
            print(
                f"{instance['id']:22s} seed {seed:2d}: "
                f"{record['cpu_time_s']:.6f}s {record['status']}",
                flush=True,
            )

    payload["completed_at"] = utc_now()
    payload["summary"] = summarize(payload)
    atomic_write(output, payload)
    comparison = payload["summary"].get("comparison")
    if comparison:
        print(json.dumps(comparison, indent=2, sort_keys=True), flush=True)
    bad = [run for run in payload["runs"] if not run_is_proven(run)]
    if bad:
        print(
            f"ERROR: {len(bad)} run(s) lack proven matching objective/bound; "
            "do not use the summary",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
