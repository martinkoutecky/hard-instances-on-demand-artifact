#!/usr/bin/env python3
"""Run published processing-time matrices under the paper's NPFS CP model.

The solver model is F_m || C_max: every job visits machines 1..m, while each
machine may use a different job order.  The source suites were not necessarily
introduced for this model; this runner deliberately re-solves their processing
matrices under the same model used for the Nevergrad champions.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import platform
import statistics
import sys
from datetime import datetime, timezone
from pathlib import Path

import docplex.cp.config as cpconfig


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent.parent
SOLVER_RUNNER = HERE.parent / "vrf_cpopt_10x5" / "run_cpopt.py"
DEFAULT_DEMIRKOL = Path(__file__).with_name("demirkol-fcmax.txt")
ATTACHMENT_CHAMPIONS = REPOSITORY / "champions" / "jssp"
DEMIRKOL_URL = (
    "https://web.archive.org/web/20030204143452id_/"
    "http://palette.ecn.purdue.edu/~uzsoy2/benchmark/fcmax.txt"
)
TAILLARD_URL = (
    "https://people.brunel.ac.uk/~mastjjb/jeb/orlib/files/flowshop2.txt"
)
TAILLARD_20X5_SEEDS = (
    873654221,
    379008056,
    1866992158,
    216771124,
    495070989,
    402959317,
    1369363414,
    2021925980,
    573109518,
    88325120,
)


def load_solver_runner():
    spec = importlib.util.spec_from_file_location("npfs_cpopt_runner", SOLVER_RUNNER)
    if spec is None or spec.loader is None:
        raise SystemExit(f"cannot import {SOLVER_RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_seeds(value: str) -> tuple[int, ...]:
    result = tuple(dict.fromkeys(int(part) for part in value.split(",") if part))
    if not result or any(seed < 0 for seed in result):
        raise argparse.ArgumentTypeError("solver seeds must be nonnegative")
    return result


def parse_demirkol(path: Path) -> list[dict]:
    lines = path.read_text(encoding="utf-8").splitlines()
    instances: list[dict] = []
    index = 0
    while index < len(lines):
        if "PROBLEM NAME" not in lines[index]:
            index += 1
            continue
        name = lines[index].split()[-1]
        lower_bound = int(lines[index + 1].split()[-1])
        upper_bound = int(lines[index + 2].split()[-1])
        index += 5
        n_jobs, n_machines = (int(x) for x in lines[index].split())
        matrix: list[list[int]] = []
        for _ in range(n_jobs):
            index += 1
            values = [int(x) for x in lines[index].split()]
            machines = values[0::2]
            durations = values[1::2]
            if machines != list(range(1, n_machines + 1)):
                raise ValueError(f"{name}: unexpected machine route {machines}")
            matrix.append(durations)
        instances.append(
            {
                "id": name,
                "n_jobs": n_jobs,
                "n_machines": n_machines,
                "matrix": matrix,
                "published_lower_bound": lower_bound,
                "published_upper_bound": upper_bound,
            }
        )
        index += 1
    if len(instances) != 40:
        raise ValueError(f"expected 40 Demirkol F//Cmax instances, found {len(instances)}")
    return instances


def taillard_matrix(seed: int, n_jobs: int = 20, n_machines: int = 5) -> list[list[int]]:
    """Generate the official matrix using Taillard's published `unif` mapping."""
    modulus = 2**31 - 1
    state = int(seed)
    matrix = [[0] * n_machines for _ in range(n_jobs)]
    for machine in range(n_machines):
        for job in range(n_jobs):
            state = (16807 * state) % modulus
            matrix[job][machine] = 1 + int((state / modulus) * 99)
    return matrix


def taillard_instances(n_jobs: int = 20, n_machines: int = 5) -> list[dict]:
    return [
        {
            "id": (
                f"ta{number:03d}"
                if (n_jobs, n_machines) == (20, 5)
                else f"taillard_gen_{n_jobs}x{n_machines}_{number:02d}"
            ),
            "n_jobs": n_jobs,
            "n_machines": n_machines,
            "matrix": taillard_matrix(seed, n_jobs, n_machines),
            "generation_seed": seed,
        }
        for number, seed in enumerate(TAILLARD_20X5_SEEDS, 1)
    ]


def attachment_instance(filename: str) -> dict:
    path = ATTACHMENT_CHAMPIONS / filename
    rows = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    n_jobs, n_machines = (int(value) for value in rows[0].split())
    matrix = [[int(value) for value in row.split()] for row in rows[1:]]
    if len(matrix) != n_jobs or any(len(row) != n_machines for row in matrix):
        raise ValueError(f"bad matrix shape in {path}")
    return {
        "id": path.stem,
        "n_jobs": n_jobs,
        "n_machines": n_machines,
        "matrix": matrix,
        "source_path": str(path),
        "source_sha256": sha256(path),
    }


def atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, path)


def summarize(payload: dict) -> dict:
    grouped: dict[str, list[dict]] = {}
    for run in payload["runs"]:
        grouped.setdefault(run["instance_id"], []).append(run)
    result = {}
    for instance_id, runs in grouped.items():
        runs.sort(key=lambda run: run["solver_seed"])
        optimal = [run for run in runs if run["status"] == "Optimal"]
        entry = {
            "statuses": [run["status"] for run in runs],
            "cpu_times_s": [run["cpu_time_s"] for run in runs],
            "all_optimal": len(optimal) == len(payload["protocol"]["solver_seeds"]),
        }
        if optimal:
            times = [float(run["cpu_time_s"]) for run in optimal]
            entry.update(
                median_optimal_cpu_s=statistics.median(times),
                min_optimal_cpu_s=min(times),
                max_optimal_cpu_s=max(times),
            )
        result[instance_id] = entry
    return {"instances": result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("demirkol", "taillard", "champion8", "champion10"),
        required=True,
    )
    parser.add_argument("--demirkol-file", type=Path, default=DEFAULT_DEMIRKOL)
    parser.add_argument(
        "--taillard-size",
        default="20x5",
        help=(
            "matrix size for --suite taillard (default: 20x5). Sizes other than "
            "20x5 are Taillard-generator instances, not members of the published "
            "120-instance benchmark suite"
        ),
    )
    parser.add_argument("--solver-seeds", type=parse_seeds, default=(1,))
    parser.add_argument("--time-limit", type=float, default=300.0)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    runner = load_solver_runner()
    cpoptimizer = runner.find_cpoptimizer()
    cpconfig.context.solver.local.execfile = cpoptimizer
    cpconfig.context.solver.local.process_start_timeout = 60

    if args.suite == "demirkol":
        source_path = args.demirkol_file.resolve()
        instances = parse_demirkol(source_path)
        source = {
            "url": DEMIRKOL_URL,
            "local_path": str(source_path),
            "sha256": sha256(source_path),
        }
    elif args.suite == "taillard":
        try:
            n_jobs, n_machines = (
                int(value) for value in args.taillard_size.lower().split("x", 1)
            )
        except ValueError as error:
            raise SystemExit("--taillard-size must have the form JOBSxMACHINES") from error
        if n_jobs <= 0 or n_machines <= 0:
            raise SystemExit("--taillard-size dimensions must be positive")
        instances = taillard_instances(n_jobs, n_machines)
        source = {
            "url": TAILLARD_URL,
            "generator": "Taillard 1993 Park-Miller RNG and floating-point unif mapping",
            "generation_seeds": list(TAILLARD_20X5_SEEDS),
            "published_benchmark_member": (n_jobs, n_machines) == (20, 5),
            "note": (
                "20x5 is in the published Taillard benchmark suite; other sizes "
                "are reproducible Taillard-generator instances using its 20x5 seeds"
            ),
        }
    elif args.suite in ("champion8", "champion10"):
        filename = (
            "champ_DiagonalCMA_8x4.txt"
            if args.suite == "champion8"
            else "champ_DE_10x5.txt"
        )
        instance = attachment_instance(filename)
        instances = [instance]
        source = {
            "official_thesis_attachment": True,
            "local_path": instance["source_path"],
            "sha256": instance["source_sha256"],
        }
    if args.limit is not None:
        instances = instances[: args.limit]

    protocol = {
        "problem": "non-permutation flow shop F_m||C_max",
        "suite": args.suite,
        "instance_ids": [instance["id"] for instance in instances],
        "solver_seeds": list(args.solver_seeds),
        "time_limit_s": args.time_limit,
        "workers": 1,
        "timing": "RUSAGE_CHILDREN user+system CPU delta",
        "solver_model_source": str(SOLVER_RUNNER),
        "source": source,
    }
    output = args.output.resolve()
    if output.exists():
        payload = json.loads(output.read_text(encoding="utf-8"))
        if payload.get("protocol") != protocol:
            raise SystemExit("existing output uses a different protocol")
        payload.setdefault("resumed_at", []).append(utc_now())
    else:
        payload = {
            "schema_version": 1,
            "created_at": utc_now(),
            "protocol": protocol,
            "machine": {
                "hostname": platform.node(),
                "cpu_model": runner.cpu_model(),
                "platform": platform.platform(),
                "python": sys.version,
                "python_executable": sys.executable,
                "cpoptimizer_path": cpoptimizer,
                "cpoptimizer_sha256": sha256(Path(cpoptimizer)),
                "cpu_affinity": sorted(os.sched_getaffinity(0)),
                "load_average_at_start": list(os.getloadavg()),
            },
            "runs": [],
        }

    done = {(run["instance_id"], run["solver_seed"]) for run in payload["runs"]}
    for solver_seed in args.solver_seeds:
        for instance in instances:
            key = (instance["id"], solver_seed)
            if key in done:
                print(f"skip checkpointed {instance['id']} seed {solver_seed}", flush=True)
                continue
            try:
                measured = runner.solve(instance["matrix"], solver_seed, args.time_limit)
            except Exception as error:  # Preserve solver/license failures as evidence.
                message = str(error)
                status = (
                    "LicenseLimit"
                    if "Problem size limit exceeded" in message
                    else "SolverError"
                )
                measured = {
                    "status": status,
                    "cpu_time_s": 0.0,
                    "wall_time_s": 0.0,
                    "error": message,
                }
            record = {
                "instance_id": instance["id"],
                "n_jobs": instance["n_jobs"],
                "n_machines": instance["n_machines"],
                "solver_seed": solver_seed,
                **measured,
            }
            payload["runs"].append(record)
            payload["summary"] = summarize(payload)
            payload["last_checkpoint_at"] = utc_now()
            atomic_write(output, payload)
            print(
                f"{instance['id']:<24} seed {solver_seed:2d}: "
                f"{record['cpu_time_s']:.6f}s {record['status']}",
                flush=True,
            )
    payload["completed_at"] = utc_now()
    payload["summary"] = summarize(payload)
    atomic_write(output, payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
