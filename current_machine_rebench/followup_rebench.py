#!/usr/bin/env python3
"""Checkpointed follow-up measurements for the ALENEX current-machine audit."""

from __future__ import annotations

import argparse
import fcntl
import heapq
import json
import math
import os
import pickle
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from run_rebench import (
    REPOSITORY,
    assert_single_cpu,
    atomic_json,
    git_revision,
    measure_concorde_with_timeout,
    sha256,
    utc_now,
    write_upper_row_tsp,
)


for variable in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ[variable] = "1"


def atomic_pickle(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        pickle.dump(value, handle, protocol=pickle.HIGHEST_PROTOCOL)
    temporary.replace(path)


def acquire_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+", encoding="utf-8")
    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def machine(affinity: list[int]) -> dict:
    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_affinity": affinity,
    }


def geometric_mean(values: list[float]) -> float:
    return math.exp(sum(math.log(max(value, 1e-12)) for value in values) / len(values))


def write_npfs(path: Path, matrix: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"{matrix.shape[0]} {matrix.shape[1]}"]
    lines.extend(" ".join(str(int(value)) for value in row) for row in matrix)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_hcp(path: Path, adjacency: np.ndarray, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    matrix = np.maximum(adjacency, np.asarray(adjacency).T)
    lines = [
        f"NAME: {name}",
        "TYPE: HCP",
        f"DIMENSION: {len(matrix)}",
        "EDGE_DATA_FORMAT: EDGE_LIST",
        "EDGE_DATA_SECTION",
    ]
    for left in range(len(matrix)):
        for right in range(left + 1, len(matrix)):
            if matrix[left, right] > 0:
                lines.append(f"{left + 1} {right + 1}")
    lines.extend(("-1", "EOF"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def npfs8_control(args: argparse.Namespace) -> int:
    affinity = assert_single_cpu()
    output = args.output.resolve()
    state_path = output.with_suffix(".state.pkl")
    lock_handle = acquire_lock(output.with_suffix(".lock"))

    jssp = REPOSITORY / "JSSP"
    sys.path.insert(0, str(jssp))
    import solution_cpopt as cpopt  # noqa: PLC0415
    sys.path.pop(0)

    protocol = {
        "kind": "npfs8_uniform_control",
        "budget": args.budget,
        "seed": args.seed,
        "screen_solver_seed": 1,
        "screen_cap_s": args.cap,
        "keep": args.keep,
        "remeasure_seeds": [1, 30],
    }
    rng = np.random.default_rng(args.seed)
    state = {
        "protocol": protocol,
        "started_at": utc_now(),
        "completed": 0,
        "heap": [],
        "remeasure": {},
    }
    if state_path.exists():
        state = pickle.loads(state_path.read_bytes())
        if state["protocol"] != protocol:
            raise SystemExit(f"checkpoint protocol mismatch in {state_path}")
        rng.bit_generator.state = state["rng_state"]

    started = time.monotonic()
    for index in range(state["completed"], args.budget):
        matrix = rng.integers(1, 101, size=(8, 4), dtype=np.int64)
        score = min(float(cpopt.solve(matrix, 8, 4, seed=1, time_limit=args.cap)), args.cap)
        item = (score, index, matrix.tolist())
        if len(state["heap"]) < args.keep:
            heapq.heappush(state["heap"], item)
        elif score > state["heap"][0][0]:
            heapq.heapreplace(state["heap"], item)
        state["completed"] = index + 1
        if state["completed"] % args.checkpoint_every == 0 or state["completed"] == args.budget:
            state["rng_state"] = rng.bit_generator.state
            atomic_pickle(state_path, state)
            best = max(state["heap"])
            print(
                f"npfs8 {state['completed']}/{args.budget} best={best[0]:.6f}s "
                f"eval={best[1]} elapsed={time.monotonic() - started:.1f}s",
                flush=True,
            )

    candidates = sorted(state["heap"], reverse=True)
    candidate_dir = output.parent / "npfs8_candidates"
    for rank, (selection_score, index, matrix_rows) in enumerate(candidates, 1):
        matrix = np.asarray(matrix_rows, dtype=np.int64)
        path = candidate_dir / f"uniform_rank{rank:02d}_eval{index:06d}.txt"
        write_npfs(path, matrix)
        key = str(index)
        measurements = state["remeasure"].setdefault(key, [])
        done = {entry["seed"] for entry in measurements}
        for seed in range(1, 31):
            if seed in done:
                continue
            measured = min(
                float(cpopt.solve(matrix, 8, 4, seed=seed, time_limit=args.cap)),
                args.cap,
            )
            measurements.append({"seed": seed, "cpu_time_s": measured})
            atomic_pickle(state_path, state)
        values = [entry["cpu_time_s"] for entry in measurements]
        print(
            f"npfs8 clean rank={rank} eval={index}: median30={statistics.median(values):.6f}s",
            flush=True,
        )

    exported = []
    for rank, (selection_score, index, matrix_rows) in enumerate(candidates, 1):
        values = [entry["cpu_time_s"] for entry in state["remeasure"][str(index)]]
        path = candidate_dir / f"uniform_rank{rank:02d}_eval{index:06d}.txt"
        exported.append(
            {
                "rank_by_screen": rank,
                "evaluation_index": index,
                "selection_score_s": selection_score,
                "file": str(path),
                "sha256": sha256(path),
                "seed_times_s": values,
                "train_median_s": statistics.median(values[:7]),
                "all30_median_s": statistics.median(values),
                "all30_geomean_s": geometric_mean(values),
            }
        )
    report = {
        "schema_version": 1,
        "protocol": protocol,
        "started_at": state["started_at"],
        "completed_at": utc_now(),
        "project_revision": git_revision(),
        "machine": machine(affinity),
        "screen_winner": exported[0],
        "conservative_best_clean": max(exported, key=lambda row: row["all30_median_s"]),
        "candidates": exported,
    }
    atomic_json(output, report)
    print(f"wrote {output}", flush=True)
    return 0


def load_tsp_modules():
    tsp_dir = REPOSITORY / "TSP"
    sys.path.insert(0, str(REPOSITORY))
    sys.path.insert(0, str(tsp_dir))
    from ng_class import My_Test  # noqa: PLC0415
    import solution_concorde  # noqa: PLC0415
    sys.path.pop(0)
    sys.path.pop(0)
    solution_concorde.set_timer("resource")
    return My_Test, solution_concorde


def load_ham_modules():
    ham_dir = REPOSITORY / "Ham"
    sys.path.insert(0, str(REPOSITORY))
    sys.path.insert(0, str(ham_dir))
    from ng_class import My_Test  # noqa: PLC0415
    import solution_concorde  # noqa: PLC0415
    sys.path.pop(0)
    sys.path.pop(0)
    solution_concorde.set_timer("resource")
    return My_Test, solution_concorde


def summarize_ham_repetitions(rows: list[dict]) -> dict:
    result = {}
    for split, seeds in (("train", range(1, 8)), ("heldout", range(8, 31))):
        seed_values = []
        raw = {}
        for seed in seeds:
            values = [
                float(row["cpu_time_s"])
                for row in rows
                if row["seed"] == seed
            ]
            if len(values) != 3:
                raise RuntimeError(f"expected three HAM repetitions for seed {seed}")
            raw[str(seed)] = values
            seed_values.append(geometric_mean(values))
        result[split] = {
            "seed_repetitions_s": raw,
            "seed_values_s": seed_values,
            "median_s": statistics.median(seed_values),
            "geomean_s": geometric_mean(seed_values),
        }
    return result


def ham_random_control(args: argparse.Namespace) -> int:
    affinity = assert_single_cpu()
    output = args.output.resolve()
    state_path = output.with_suffix(".state.pkl")
    lock_handle = acquire_lock(output.with_suffix(".lock"))
    My_Test, solver = load_ham_modules()

    protocol = {
        "kind": "ham_uniform_genome_randomsearch",
        "encoding": args.encoding,
        "budget": args.budget,
        "seed": args.seed,
        "screen_solver_seed": 1,
        "screen_repetitions": 1,
        "keep": args.keep,
        "cap_s": args.cap,
        "clean_repetitions_per_seed": 3,
        "train_seeds": [1, 7],
        "heldout_seeds": [8, 30],
        "sampling": "Nevergrad encoding parameter.sample()",
    }
    factory = My_Test(
        20,
        encoding=args.encoding,
        undirected=True,
        solver="concorde",
        solver_seed=1,
    )
    parameter = factory.encode()
    parameter.random_state.seed(args.seed)
    state = {
        "protocol": protocol,
        "started_at": utc_now(),
        "next_index": 0,
        "heap": [],
        "remeasure": {},
    }
    if state_path.exists():
        state = pickle.loads(state_path.read_bytes())
        if state["protocol"] != protocol:
            raise SystemExit(f"checkpoint protocol mismatch in {state_path}")
        parameter.random_state.set_state(state["random_state"])

    started = time.monotonic()
    for index in range(state["next_index"], args.budget):
        genome = parameter.sample().value
        adjacency = factory.decode_test(genome)
        score = min(float(solver.solve(adjacency, 20, seed=1)), args.cap)
        item = (score, index, adjacency.tolist())
        if len(state["heap"]) < args.keep:
            heapq.heappush(state["heap"], item)
        elif score > state["heap"][0][0]:
            heapq.heapreplace(state["heap"], item)
        state["next_index"] = index + 1
        if state["next_index"] % args.checkpoint_every == 0:
            state["random_state"] = parameter.random_state.get_state()
            atomic_pickle(state_path, state)
            best = max(state["heap"])
            print(
                f"ham-rs {args.encoding} {state['next_index']}/{args.budget} "
                f"best={best[0]:.6f}s eval={best[1]} "
                f"elapsed={time.monotonic() - started:.1f}s",
                flush=True,
            )
    state["random_state"] = parameter.random_state.get_state()
    atomic_pickle(state_path, state)

    candidates = sorted(state["heap"], reverse=True)
    candidate_dir = output.parent / "ham_random_candidates" / args.encoding
    exported = []
    for rank, (selection_score, index, adjacency_rows) in enumerate(candidates, 1):
        adjacency = np.asarray(adjacency_rows, dtype=np.int8)
        path = candidate_dir / f"rank{rank:02d}_eval{index:06d}.hcp"
        write_hcp(path, adjacency, f"ham_rs_{args.encoding}_{rank:02d}")
        key = str(index)
        measurements = state["remeasure"].setdefault(key, [])
        done = {(row["seed"], row["repeat"]) for row in measurements}
        for seed in range(1, 31):
            for repeat in range(3):
                if (seed, repeat) in done:
                    continue
                value = min(float(solver.solve(adjacency, 20, seed=seed)), args.cap)
                measurements.append(
                    {"seed": seed, "repeat": repeat, "cpu_time_s": value}
                )
                atomic_pickle(state_path, state)
        clean = summarize_ham_repetitions(measurements)
        exported.append(
            {
                "rank_by_screen": rank,
                "evaluation_index": index,
                "selection_score_s": selection_score,
                "file": str(path),
                "sha256": sha256(path),
                "clean": clean,
            }
        )
        print(
            f"ham-rs {args.encoding} clean rank={rank} eval={index}: "
            f"{clean['train']['median_s']:.6f}s / "
            f"{clean['heldout']['median_s']:.6f}s",
            flush=True,
        )

    report = {
        "schema_version": 1,
        "protocol": protocol,
        "started_at": state["started_at"],
        "completed_at": utc_now(),
        "project_revision": git_revision(),
        "machine": machine(affinity),
        "selection_winner": exported[0],
        "conservative_best_clean_train": max(
            exported, key=lambda row: row["clean"]["train"]["median_s"]
        ),
        "conservative_best_clean_heldout": max(
            exported, key=lambda row: row["clean"]["heldout"]["median_s"]
        ),
        "candidates": exported,
    }
    atomic_json(output, report)
    print(f"wrote {output}", flush=True)
    return 0


def evaluate_tsp_train(matrix: np.ndarray, solver, cap: float) -> dict:
    seed_values = []
    raw = {}
    for seed in range(1, 8):
        values = [min(float(solver.solve(matrix, 20, seed=seed)), cap) for _ in range(3)]
        raw[str(seed)] = values
        seed_values.append(geometric_mean(values))
    return {
        "seed_repetitions_s": raw,
        "seed_values_s": seed_values,
        "score_s": statistics.median(seed_values),
        "geomean_s": geometric_mean(seed_values),
    }


def tsp_random_shard(args: argparse.Namespace) -> int:
    affinity = assert_single_cpu()
    output = args.output.resolve()
    state_path = output.with_suffix(".state.pkl")
    lock_handle = acquire_lock(output.with_suffix(".lock"))
    My_Test, solver = load_tsp_modules()

    protocol = {
        "kind": "tsp_randomsearch_exact_objective_shard",
        "budget": args.budget,
        "seed": args.seed,
        "keep": args.keep,
        "cap_s": args.cap,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "objective": "median across seeds 1..7 of geomean across 3 repetitions",
        "sampling": "Nevergrad bounded Array parameter.sample()",
    }
    factory = My_Test(20, 1, 1000)
    parameter = factory.encode()
    parameter.random_state.seed(args.seed)
    state = {
        "protocol": protocol,
        "started_at": utc_now(),
        "next_index": 0,
        "evaluated": 0,
        "heap": [],
    }
    if state_path.exists():
        state = pickle.loads(state_path.read_bytes())
        if state["protocol"] != protocol:
            raise SystemExit(f"checkpoint protocol mismatch in {state_path}")
        parameter.random_state.set_state(state["random_state"])

    started = time.monotonic()
    for index in range(state["next_index"], args.budget):
        sampled = parameter.sample().value
        state["next_index"] = index + 1
        if index % args.shard_count != args.shard_index:
            continue
        encoded = [int(round(float(value))) for value in sampled]
        matrix = factory.decode_test(encoded)
        measurement = evaluate_tsp_train(matrix, solver, args.cap)
        score = float(measurement["score_s"])
        item = (score, index, encoded, measurement)
        if len(state["heap"]) < args.keep:
            heapq.heappush(state["heap"], item)
        elif score > state["heap"][0][0]:
            heapq.heapreplace(state["heap"], item)
        state["evaluated"] += 1
        if state["evaluated"] % args.checkpoint_every == 0:
            state["random_state"] = parameter.random_state.get_state()
            atomic_pickle(state_path, state)
            best = max(state["heap"])
            print(
                f"tsp-rs shard={args.shard_index} evaluated={state['evaluated']} "
                f"next={state['next_index']}/{args.budget} best={best[0]:.6f}s "
                f"eval={best[1]} elapsed={time.monotonic() - started:.1f}s",
                flush=True,
            )
    state["random_state"] = parameter.random_state.get_state()
    atomic_pickle(state_path, state)

    candidates = []
    for rank, (score, index, encoded, measurement) in enumerate(sorted(state["heap"], reverse=True), 1):
        candidates.append(
            {
                "rank_within_shard": rank,
                "evaluation_index": index,
                "selection_score_s": score,
                "encoded_upper_triangle": encoded,
                "selection_measurement": measurement,
            }
        )
    report = {
        "schema_version": 1,
        "protocol": protocol,
        "started_at": state["started_at"],
        "completed_at": utc_now(),
        "project_revision": git_revision(),
        "machine": machine(affinity),
        "evaluated": state["evaluated"],
        "candidates": candidates,
    }
    atomic_json(output, report)
    print(f"wrote {output}", flush=True)
    return 0


def tsp_random_prepare(args: argparse.Namespace) -> int:
    output = args.output.resolve()
    reports = [json.loads(path.read_text()) for path in args.shards]
    candidates = [candidate for report in reports for candidate in report["candidates"]]
    candidates.sort(key=lambda row: (row["selection_score_s"], row["evaluation_index"]), reverse=True)
    candidates = candidates[: args.keep]
    My_Test, _ = load_tsp_modules()
    factory = My_Test(20, 1, 1000)
    candidate_dir = output.parent / "tsp_random_candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    exported = []
    for rank, candidate in enumerate(candidates, 1):
        matrix = factory.decode_test(candidate["encoded_upper_triangle"])
        path = candidate_dir / f"rank{rank:02d}_eval{candidate['evaluation_index']:06d}.tsp"
        write_upper_row_tsp(path, matrix, f"tsp_rs_rank{rank:02d}")
        exported.append(
            {
                **candidate,
                "rank_by_selection_score": rank,
                "file": str(path),
                "sha256": sha256(path),
            }
        )
    manifest = {
        "schema_version": 1,
        "created_at": utc_now(),
        "project_revision": git_revision(),
        "source_shards": [str(path.resolve()) for path in args.shards],
        "budget": sum(report["evaluated"] for report in reports),
        "candidates": exported,
    }
    atomic_json(output, manifest)
    print(f"wrote {output}", flush=True)
    return 0


def tsp_random_remeasure(args: argparse.Namespace) -> int:
    affinity = assert_single_cpu()
    manifest = json.loads(args.candidates.read_text())
    output = args.output.resolve()
    lock_handle = acquire_lock(output.with_suffix(".lock"))
    protocol = {
        "kind": "tsp_randomsearch_clean_remeasurement_shard",
        "candidate_manifest": str(args.candidates.resolve()),
        "candidate_manifest_sha256": sha256(args.candidates.resolve()),
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "repetitions_per_seed": 3,
        "train_seeds": [1, 7],
        "heldout_seeds": [8, 30],
        "cap_s": args.cap,
    }
    report = {
        "schema_version": 1,
        "protocol": protocol,
        "started_at": utc_now(),
        "project_revision": git_revision(),
        "machine": machine(affinity),
        "runs": [],
    }
    if output.exists():
        report = json.loads(output.read_text())
        if report["protocol"] != protocol:
            raise SystemExit(f"checkpoint protocol mismatch in {output}")
    done = {
        (row["evaluation_index"], row["split"], row["seed"], row["repeat"])
        for row in report["runs"]
        if row["status"] != "ERROR"
    }
    selected = [
        row
        for row in manifest["candidates"]
        if (row["rank_by_selection_score"] - 1) % args.shard_count == args.shard_index
    ]
    for candidate in selected:
        for split, seeds in (("train", range(1, 8)), ("heldout", range(8, 31))):
            for seed in seeds:
                for repeat in range(3):
                    key = (candidate["evaluation_index"], split, seed, repeat)
                    if key in done:
                        continue
                    measured = measure_concorde_with_timeout(
                        "tsp_generated", Path(candidate["file"]), seed, args.cap
                    )
                    report["runs"].append(
                        {
                            "evaluation_index": candidate["evaluation_index"],
                            "rank_by_selection_score": candidate["rank_by_selection_score"],
                            "file": candidate["file"],
                            "split": split,
                            "seed": seed,
                            "repeat": repeat,
                            **measured,
                        }
                    )
                    atomic_json(output, report)
                    if measured["status"] == "ERROR":
                        raise RuntimeError(measured["error"])
        print(
            f"tsp-rs clean shard={args.shard_index} rank={candidate['rank_by_selection_score']} done",
            flush=True,
        )
    report["completed_at"] = utc_now()
    atomic_json(output, report)
    print(f"wrote {output}", flush=True)
    return 0


def summarize_tsp_rows(rows: list[dict]) -> dict:
    result = {}
    for split in ("train", "heldout"):
        split_rows = [row for row in rows if row["split"] == split]
        seed_values = []
        for seed in sorted({row["seed"] for row in split_rows}):
            repetitions = [
                min(float(row.get("cpu_time_s", row.get("cap_s", 60.0))), 60.0)
                for row in split_rows
                if row["seed"] == seed
            ]
            seed_values.append(geometric_mean(repetitions))
        result[split] = {
            "seed_values_s": seed_values,
            "median_s": statistics.median(seed_values),
            "geomean_s": geometric_mean(seed_values),
        }
    return result


def tsp_random_finalize(args: argparse.Namespace) -> int:
    manifest = json.loads(args.candidates.read_text())
    reports = [json.loads(path.read_text()) for path in args.remeasure]
    runs = [row for report in reports for row in report["runs"]]
    summaries = []
    for candidate in manifest["candidates"]:
        candidate_rows = [
            row for row in runs if row["evaluation_index"] == candidate["evaluation_index"]
        ]
        summaries.append({**candidate, "clean": summarize_tsp_rows(candidate_rows)})
    output = {
        "schema_version": 1,
        "completed_at": utc_now(),
        "project_revision": git_revision(),
        "candidate_manifest": str(args.candidates.resolve()),
        "source_remeasurements": [str(path.resolve()) for path in args.remeasure],
        "selection_winner": summaries[0],
        "conservative_best_clean_train": max(
            summaries, key=lambda row: row["clean"]["train"]["median_s"]
        ),
        "conservative_best_clean_heldout": max(
            summaries, key=lambda row: row["clean"]["heldout"]["median_s"]
        ),
        "candidates": summaries,
    }
    atomic_json(args.output.resolve(), output)
    print(f"wrote {args.output.resolve()}", flush=True)
    return 0


def tsp_fixed(args: argparse.Namespace) -> int:
    affinity = assert_single_cpu()
    output = args.output.resolve()
    lock_handle = acquire_lock(output.with_suffix(".lock"))
    family = "tsplib" if args.case == "gr229" else "hard_tsplib"
    path = args.external_dir.resolve() / "instances" / family / f"{args.case}.tsp"
    protocol = {
        "kind": "tsp_fixed_external",
        "case": args.case,
        "source": str(path),
        "source_sha256": sha256(path),
        "repetitions_per_seed": 3,
        "train_seeds": [1, 7],
        "heldout_seeds": [8, 30],
        "cap_s": args.cap,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
    }
    report = {
        "schema_version": 1,
        "protocol": protocol,
        "started_at": utc_now(),
        "project_revision": git_revision(),
        "machine": machine(affinity),
        "runs": [],
    }
    if output.exists():
        report = json.loads(output.read_text())
        if report["protocol"] != protocol:
            raise SystemExit(f"checkpoint protocol mismatch in {output}")
    done = {
        (row["split"], row["seed"], row["repeat"])
        for row in report["runs"]
        if row["status"] != "ERROR"
    }
    ordinal = 0
    for split, seeds in (("train", range(1, 8)), ("heldout", range(8, 31))):
        for seed in seeds:
            for repeat in range(3):
                assigned = ordinal % args.shard_count == args.shard_index
                ordinal += 1
                if not assigned:
                    continue
                key = (split, seed, repeat)
                if key in done:
                    continue
                measured = measure_concorde_with_timeout("tsp_native", path, seed, args.cap)
                report["runs"].append(
                    {"split": split, "seed": seed, "repeat": repeat, **measured}
                )
                atomic_json(output, report)
                if measured["status"] == "ERROR":
                    raise RuntimeError(measured["error"])
                print(
                    f"{args.case} {split} seed={seed} rep={repeat}: "
                    f"{measured['status']} {measured.get('cpu_time_s', args.cap):.6f}s",
                    flush=True,
                )
    if args.shard_count == 1:
        report["summary"] = summarize_tsp_rows(report["runs"])
    report["completed_at"] = utc_now()
    atomic_json(output, report)
    print(f"wrote {output}", flush=True)
    return 0


def tsp_fixed_finalize(args: argparse.Namespace) -> int:
    reports = [json.loads(path.read_text()) for path in args.shards]
    base = reports[0]["protocol"]
    for report in reports[1:]:
        protocol = report["protocol"]
        for key in (
            "kind",
            "case",
            "source",
            "source_sha256",
            "repetitions_per_seed",
            "train_seeds",
            "heldout_seeds",
            "cap_s",
            "shard_count",
        ):
            if protocol[key] != base[key]:
                raise SystemExit(f"fixed-comparator shard mismatch for {key}")
    runs = [row for report in reports for row in report["runs"]]
    expected = 30 * 3
    if len(runs) != expected:
        raise SystemExit(f"expected {expected} fixed-comparator runs, found {len(runs)}")
    output = {
        "schema_version": 1,
        "completed_at": utc_now(),
        "project_revision": git_revision(),
        "protocol": {key: value for key, value in base.items() if key != "shard_index"},
        "source_shards": [str(path.resolve()) for path in args.shards],
        "runs": runs,
        "summary": summarize_tsp_rows(runs),
    }
    atomic_json(args.output.resolve(), output)
    print(f"wrote {args.output.resolve()}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    npfs = sub.add_parser("npfs8-control")
    npfs.add_argument("--output", type=Path, required=True)
    npfs.add_argument("--budget", type=int, default=100_000)
    npfs.add_argument("--seed", type=int, default=20_260_601)
    npfs.add_argument("--keep", type=int, default=20)
    npfs.add_argument("--cap", type=float, default=60.0)
    npfs.add_argument("--checkpoint-every", type=int, default=100)
    npfs.set_defaults(func=npfs8_control)

    ham = sub.add_parser("ham-random-control")
    ham.add_argument("--encoding", choices=("trivial", "perm_int", "perm_thr"), required=True)
    ham.add_argument("--output", type=Path, required=True)
    ham.add_argument("--budget", type=int, default=100_000)
    ham.add_argument("--seed", type=int, default=20_260_719)
    ham.add_argument("--keep", type=int, default=20)
    ham.add_argument("--cap", type=float, default=60.0)
    ham.add_argument("--checkpoint-every", type=int, default=250)
    ham.set_defaults(func=ham_random_control)

    shard = sub.add_parser("tsp-random-shard")
    shard.add_argument("--output", type=Path, required=True)
    shard.add_argument("--budget", type=int, default=100_000)
    shard.add_argument("--seed", type=int, default=20_260_601)
    shard.add_argument("--keep", type=int, default=20)
    shard.add_argument("--cap", type=float, default=60.0)
    shard.add_argument("--checkpoint-every", type=int, default=50)
    shard.add_argument("--shard-index", type=int, required=True)
    shard.add_argument("--shard-count", type=int, default=4)
    shard.set_defaults(func=tsp_random_shard)

    prepare = sub.add_parser("tsp-random-prepare")
    prepare.add_argument("--shards", type=Path, nargs="+", required=True)
    prepare.add_argument("--keep", type=int, default=20)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.set_defaults(func=tsp_random_prepare)

    remeasure = sub.add_parser("tsp-random-remeasure")
    remeasure.add_argument("--candidates", type=Path, required=True)
    remeasure.add_argument("--output", type=Path, required=True)
    remeasure.add_argument("--cap", type=float, default=60.0)
    remeasure.add_argument("--shard-index", type=int, required=True)
    remeasure.add_argument("--shard-count", type=int, default=4)
    remeasure.set_defaults(func=tsp_random_remeasure)

    finalize = sub.add_parser("tsp-random-finalize")
    finalize.add_argument("--candidates", type=Path, required=True)
    finalize.add_argument("--remeasure", type=Path, nargs="+", required=True)
    finalize.add_argument("--output", type=Path, required=True)
    finalize.set_defaults(func=tsp_random_finalize)

    fixed = sub.add_parser("tsp-fixed")
    fixed.add_argument("--case", choices=("gr229", "20009_hard"), required=True)
    fixed.add_argument("--external-dir", type=Path, required=True)
    fixed.add_argument("--output", type=Path, required=True)
    fixed.add_argument("--cap", type=float, default=60.0)
    fixed.add_argument("--shard-index", type=int, default=0)
    fixed.add_argument("--shard-count", type=int, default=1)
    fixed.set_defaults(func=tsp_fixed)

    fixed_finalize = sub.add_parser("tsp-fixed-finalize")
    fixed_finalize.add_argument("--shards", type=Path, nargs="+", required=True)
    fixed_finalize.add_argument("--output", type=Path, required=True)
    fixed_finalize.set_defaults(func=tsp_fixed_finalize)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
