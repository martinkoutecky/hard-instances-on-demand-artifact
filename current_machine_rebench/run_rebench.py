#!/usr/bin/env python3
"""Serial, checkpointed remeasurement of paper instances on one logical CPU."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import multiprocessing as mp
import os
import platform
import signal
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from sat_common import (
    branch_names,
    measure_branch,
    parse_dimacs,
    portfolio_members,
    sha256,
    solver_inventory,
)


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent

for variable in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ[variable] = "1"


TSP_CASES = {
    "control_matrix_best_find": "todo_instances/tsp/rs_matrix_find.tsp",
    "control_matrix_best_heldout": "todo_instances/tsp/rs_matrix_heldout.tsp",
    "control_random_euclidean": "todo_instances/tsp/euclid.tsp",
    "champion_cma": "champions/tsp/champ_CMA_dm_neg_p_it4.tsp",
    "champion_shiwa": "champions/tsp/champ_Shiwa_dm_log_p_it2.tsp",
    "champion_diagonalcma_u10000": "champions/tsp/champ_DiagonalCMA_U10000.tsp",
}

HAM_CASES = {
    "control_randomsearch_trivial": "todo_instances/ham/rs_triv.hcp",
    "control_randomsearch_perm_int": "todo_instances/ham/rs_pint.hcp",
    "control_randomsearch_perm_thr": "todo_instances/ham/rs_pthr.hcp",
    "control_gnp20_022": "todo_instances/ham/gnp20_022.hcp",
    "control_cubic20": "todo_instances/ham/cubic20.hcp",
    "champion_twopointsde": "champions/ham/champ_TwoPointsDE_pthr.hcp",
    "champion_ngoptrw": "champions/ham/champ_NGOptRW_triv.hcp",
    "champion_discretebso": "champions/ham/champ_DiscreteBSO_pthr.hcp",
}

NPFS_CASES = {
    "control_6x4_cpsat": {
        "path": "todo_instances/jssp/uniform_6x4_cpsat.txt",
        "own_engine": "cpsat",
        "train_engines": ("cpsat", "cpopt"),
        "heldout": True,
        "cap": 60.0,
    },
    "control_6x4_cpopt": {
        "path": "todo_instances/jssp/uniform_6x4_cpopt.txt",
        "own_engine": "cpopt",
        "train_engines": ("cpsat", "cpopt"),
        "heldout": True,
        "cap": 60.0,
    },
    "champion_6x4_cpsat": {
        "path": "todo_instances/jssp/champ_MetaModelDiagonalCMA_6x4.txt",
        "own_engine": "cpsat",
        "train_engines": ("cpsat", "cpopt"),
        "heldout": True,
        "cap": 60.0,
    },
    "champion_6x4_cpopt": {
        "path": "champions/jssp/champ_ChainCMAwithR_6x4.txt",
        "own_engine": "cpopt",
        "train_engines": ("cpsat", "cpopt"),
        "heldout": True,
        "cap": 60.0,
    },
    "control_8x4_cpopt": {
        "path": "todo_instances/jssp/uniform_8x4_cpsat.txt",
        "own_engine": "cpopt",
        "train_engines": ("cpopt",),
        "heldout": False,
        "cap": 60.0,
    },
    "champion_8x4_cpopt": {
        "path": "champions/jssp/champ_DiagonalCMA_8x4.txt",
        "own_engine": "cpopt",
        "train_engines": ("cpsat", "cpopt"),
        "heldout": True,
        "cap": 60.0,
    },
    "control_10x5_cpopt": {
        "path": "todo_instances/jssp/rs_uniform_10x5.txt",
        "own_engine": "cpopt",
        "train_engines": ("cpopt",),
        "heldout": False,
        "cap": 600.0,
    },
    "champion_10x5_cpopt": {
        "path": "champions/jssp/champ_DE_10x5.txt",
        "own_engine": "cpopt",
        "train_engines": ("cpsat", "cpopt"),
        "heldout": True,
        "cap": 600.0,
    },
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def cpu_model() -> str:
    for line in Path("/proc/cpuinfo").read_text().splitlines():
        if line.lower().startswith("model name"):
            return line.split(":", 1)[1].strip()
    return platform.processor()


def git_revision() -> str:
    """Identify HEAD and any tracked or untracked working-tree inputs."""
    head = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "rev-parse", "HEAD"], text=True
    ).strip()
    tracked = subprocess.check_output(
        ["git", "-C", str(REPOSITORY), "diff", "--binary", "HEAD"]
    )
    untracked = subprocess.check_output(
        [
            "git",
            "-C",
            str(REPOSITORY),
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
        ]
    ).split(b"\0")
    untracked = [relative for relative in untracked if relative]
    if not tracked and not untracked:
        return head
    digest = hashlib.sha256(tracked)
    for encoded in sorted(untracked):
        relative = encoded.decode("utf-8", errors="surrogateescape")
        path = REPOSITORY / relative
        digest.update(encoded + b"\0")
        if path.is_file():
            digest.update(sha256(path).encode("ascii"))
    return f"{head}-dirty-{digest.hexdigest()}"


def directory_digest(path: Path | None, pattern: str) -> str | None:
    """Hash relative names and contents used by a resumable campaign."""
    if path is None:
        return None
    files = sorted(candidate for candidate in path.rglob(pattern) if candidate.is_file())
    digest = hashlib.sha256()
    for candidate in files:
        digest.update(str(candidate.relative_to(path)).encode("utf-8") + b"\0")
        digest.update(sha256(candidate).encode("ascii") + b"\n")
    return digest.hexdigest()


def validate_external_inputs(path: Path) -> dict:
    """Verify a complete prepared benchmark package before measuring it."""
    manifest_path = path / "prepared_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"missing prepared benchmark manifest {manifest_path}")
    prepared = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_counts = {
        "tsplib": 58,
        "hard_tsplib": 40,
        "fhcp": 11,
        "clustered_euclidean": 12,
        "sat": 3,
    }
    families = prepared.get("families", {})
    if set(families) != set(expected_counts):
        raise RuntimeError(
            f"prepared families are {sorted(families)}, expected {sorted(expected_counts)}"
        )
    for family, expected_count in expected_counts.items():
        entries = families[family]
        if len(entries) != expected_count:
            raise RuntimeError(
                f"prepared {family} has {len(entries)} entries, expected {expected_count}"
            )
        listed_paths = set()
        for entry in entries:
            source = path / entry["path"]
            listed_paths.add(source.resolve())
            if not source.is_file():
                raise FileNotFoundError(f"prepared benchmark is missing {source}")
            actual = sha256(source)
            if actual != entry["sha256"]:
                raise RuntimeError(
                    f"prepared benchmark hash changed for {source}: "
                    f"{actual} != {entry['sha256']}"
                )
        family_dir = path / "instances" / family
        actual_paths = {
            candidate.resolve()
            for candidate in family_dir.iterdir()
            if candidate.is_file()
        }
        if actual_paths != listed_paths:
            raise RuntimeError(
                f"prepared {family} files differ from its manifest: "
                f"extra={sorted(str(value) for value in actual_paths - listed_paths)}, "
                f"missing={sorted(str(value) for value in listed_paths - actual_paths)}"
            )
    return {
        "manifest_sha256": sha256(manifest_path),
        "family_counts": expected_counts,
    }


def assert_single_cpu() -> list[int]:
    affinity = sorted(os.sched_getaffinity(0))
    if len(affinity) != 1:
        raise SystemExit(
            f"single-core campaign requires one-CPU affinity, got {affinity}; "
            "launch through run_all.sh or taskset -c CPU"
        )
    return affinity


def parse_tsp(path: Path) -> np.ndarray:
    lines = path.read_text(encoding="utf-8").splitlines()
    dimension = None
    start = None
    for index, line in enumerate(lines):
        normalized = line.replace(":", " ").split()
        if normalized and normalized[0] == "DIMENSION":
            dimension = int(normalized[1])
        if line.strip() == "EDGE_WEIGHT_SECTION":
            start = index + 1
            break
    if dimension is None or start is None:
        raise ValueError(f"unsupported TSP file {path}")
    values: list[int] = []
    for line in lines[start:]:
        if line.strip() == "EOF":
            break
        values.extend(int(value) for value in line.split())
    expected = dimension * (dimension - 1) // 2
    if len(values) != expected:
        raise ValueError(f"{path}: expected {expected} upper-row values, got {len(values)}")
    matrix = np.zeros((dimension, dimension), dtype=np.int64)
    cursor = 0
    for row in range(dimension):
        for column in range(row + 1, dimension):
            matrix[row, column] = matrix[column, row] = values[cursor]
            cursor += 1
    return matrix


def parse_hcp(path: Path) -> np.ndarray:
    lines = path.read_text(encoding="utf-8").splitlines()
    dimension = None
    start = None
    for index, line in enumerate(lines):
        normalized = line.replace(":", " ").split()
        if normalized and normalized[0] == "DIMENSION":
            dimension = int(normalized[1])
        if line.strip() == "EDGE_DATA_SECTION":
            start = index + 1
            break
    if dimension is None or start is None:
        raise ValueError(f"unsupported HCP file {path}")
    adjacency = np.zeros((dimension, dimension), dtype=np.int8)
    for line in lines[start:]:
        if line.strip() in ("-1", "EOF"):
            break
        left, right = (int(value) - 1 for value in line.split())
        adjacency[left, right] = adjacency[right, left] = 1
    return adjacency


def arm_cpu_timer(cap: float) -> None:
    """Terminate this disposable worker after ``cap`` process-CPU seconds."""
    signal.signal(signal.SIGPROF, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_PROF, cap)


def cancel_cpu_timer() -> None:
    signal.setitimer(signal.ITIMER_PROF, 0.0)


def write_upper_row_tsp(path: Path, matrix: np.ndarray, name: str) -> None:
    """Write the exact explicit format used by the archived Concorde wrappers."""
    integer = np.rint(np.asarray(matrix)).astype(np.int64)
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"NAME: {name}\nTYPE: TSP\nDIMENSION: {len(integer)}\n")
        handle.write("EDGE_WEIGHT_TYPE: EXPLICIT\n")
        handle.write("EDGE_WEIGHT_FORMAT: UPPER_ROW\nEDGE_WEIGHT_SECTION\n")
        for row in range(len(integer)):
            handle.write(
                " ".join(
                    str(int(integer[row, column]))
                    for column in range(row + 1, len(integer))
                )
                + "\n"
            )
        handle.write("EOF\n")


def _solve_native_tsp(path: Path, seed: int, scratch: Path, cap: float) -> float:
    """Solve an unmodified TSPLIB file with Concorde's native parser."""
    from concorde._concorde import _CCtsp_solve_dat, _CCutil_gettsplib

    old_cwd = os.getcwd()
    devnull = os.open(os.devnull, os.O_WRONLY)
    old_stdout, old_stderr = os.dup(1), os.dup(2)
    os.dup2(devnull, 1)
    os.dup2(devnull, 2)
    try:
        os.chdir(scratch)
        ncount, data = _CCutil_gettsplib(str(path))
        started = time.process_time()
        arm_cpu_timer(cap)
        _CCtsp_solve_dat(ncount, data, uuid.uuid4().hex[:9], -1, True, seed)
        elapsed = time.process_time() - started
        cancel_cpu_timer()
        return elapsed
    finally:
        os.chdir(old_cwd)
        os.dup2(old_stdout, 1)
        os.dup2(old_stderr, 2)
        os.close(old_stdout)
        os.close(old_stderr)
        os.close(devnull)


def _concorde_child(
    connection, kind: str, path: str, seed: int, scratch: str, cap: float
) -> None:
    try:
        source = Path(path)
        if kind == "tsp_native":
            elapsed = _solve_native_tsp(source, seed, Path(scratch), cap)
        elif kind == "tsp_generated":
            instance = parse_tsp(source)
            generated = Path(scratch) / "generated.tsp"
            write_upper_row_tsp(generated, instance, "t")
            elapsed = _solve_native_tsp(generated, seed, Path(scratch), cap)
        elif kind == "ham":
            instance = parse_hcp(source)
            weights = np.where(np.maximum(instance, instance.T) > 0, 0, 1)
            generated = Path(scratch) / "generated.tsp"
            write_upper_row_tsp(generated, weights, "ham")
            elapsed = _solve_native_tsp(generated, seed, Path(scratch), cap)
        else:
            raise ValueError(f"unknown Concorde input kind {kind}")
        connection.send({"raw_cpu_s": elapsed, "status": "SOLVED"})
    except BaseException as error:
        connection.send({"status": "ERROR", "error": repr(error)})
    finally:
        cancel_cpu_timer()
        connection.close()


def measure_concorde_with_timeout(kind: str, path: Path, seed: int, cap: float) -> dict:
    """Run one seeded Concorde call in a fresh child with a process-CPU cap."""
    context = mp.get_context("fork")
    parent, child = context.Pipe(duplex=False)
    scratch = Path(tempfile.mkdtemp(prefix="paper_concorde_"))
    process = context.Process(
        target=_concorde_child,
        args=(child, kind, str(path.resolve()), seed, str(scratch), cap),
    )
    wall_started = time.perf_counter()
    process.start()
    child.close()
    # SIGPROF enforces the process-CPU cap around only the solver call. This
    # larger wall guard is solely a deadlock/crash safeguard and is never
    # reported as a solver timeout.
    wall_guard = max(30.0, 5.0 * cap)
    worker_eof = False
    if parent.poll(wall_guard):
        try:
            measured = parent.recv()
        except EOFError:
            worker_eof = True
            measured = {"status": "ERROR", "error": "worker EOF"}
    else:
        process.kill()
        measured = {
            "status": "ERROR",
            "error": f"worker exceeded {wall_guard:g} s wall safety guard",
        }
    process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=2)
    wall_elapsed = time.perf_counter() - wall_started
    if worker_eof and process.exitcode == -signal.SIGPROF:
        measured = {"status": "TIMEOUT"}
    parent.close()
    shutil.rmtree(scratch, ignore_errors=True)
    raw_cpu = measured.get("raw_cpu_s")
    if raw_cpu is not None and float(raw_cpu) > cap:
        measured["status"] = "TIMEOUT"
    measured["cpu_time_s"] = (
        float(raw_cpu) if measured["status"] == "SOLVED" and raw_cpu is not None else cap
    )
    measured["wall_time_s"] = wall_elapsed
    measured["cap_s"] = cap
    return measured


def parse_npfs(path: Path) -> list[list[int]]:
    rows = [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    n_jobs, n_machines = (int(value) for value in rows[0].split())
    matrix = [[int(value) for value in row.split()] for row in rows[1:]]
    if len(matrix) != n_jobs or any(len(row) != n_machines for row in matrix):
        raise ValueError(f"bad NPFS matrix shape in {path}")
    return matrix


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sat_cases(randomsearch_dir: Path | None) -> list[dict]:
    cases = [
        {
            "id": "phase_transition",
            "path": REPOSITORY / "todo_instances/sat/phase_transition.cnf",
            "portfolio": "original3",
        },
        {
            "id": "recovered_stage1_randomsearch_mprefix",
            "path": REPOSITORY / "todo_instances/sat/rs_mpfx.cnf",
            "portfolio": "original3",
        },
        {
            "id": "champion_kcnf",
            "path": REPOSITORY / "champions/sat/champ_MultiScaleCMA_kcnf_gt1s2L.cnf",
            "portfolio": "original3",
        },
        {
            "id": "champion_mprefix",
            "path": REPOSITORY / "champions/sat/champ_TripleCMA_mpfx_gt1s2L.cnf",
            "portfolio": "original3",
        },
    ]
    for path in sorted((REPOSITORY / "dpll4_portfolio/instances").glob("*.cnf")):
        cases.append({"id": f"dpll4_{path.stem}", "path": path, "portfolio": "dpll4"})
    # Measure the old champions under the new branches as an explicit transfer check.
    for old in cases[2:4]:
        cases.append({"id": f"transfer_{old['id']}", "path": old["path"], "portfolio": "dpll4"})
    if randomsearch_dir and randomsearch_dir.exists():
        for path in sorted((randomsearch_dir / "candidates").glob("*.cnf")):
            portfolio = "dpll4" if path.name.startswith("dpll4_") else "original3"
            cases.append({"id": f"fresh_rs_{path.stem}", "path": path, "portfolio": portfolio})
    return cases


def _sat_child(connection, branch: str, path: str, portfolio: str, cap: float) -> None:
    try:
        clauses, n_vars = parse_dimacs(Path(path))
        connection.send(measure_branch(branch, clauses, n_vars, cap, portfolio=portfolio))
    except BaseException as error:
        connection.send({"branch": branch, "status": "ERROR", "error": repr(error)})
    finally:
        connection.close()


def measure_sat_with_timeout(branch: str, path: Path, portfolio: str, cap: float) -> dict:
    context = mp.get_context("fork")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_sat_child, args=(child, branch, str(path), portfolio, cap))
    process.start()
    child.close()
    grace = 70.0 if branch == "breakid_cadical195" else 10.0
    if parent.poll(cap + grace):
        try:
            result = parent.recv()
        except EOFError:
            result = {"branch": branch, "status": "ERROR", "error": "worker EOF"}
    else:
        process.kill()
        result = {
            "branch": branch,
            "raw_cpu_s": cap,
            "charged_cpu_s": cap,
            "status": "TIMEOUT",
        }
    process.join(timeout=5)
    parent.close()
    return result


def make_report(output: Path, affinity: list[int], protocol: dict) -> dict:
    if output.exists():
        report = json.loads(output.read_text(encoding="utf-8"))
        if report.get("protocol") != protocol:
            raise SystemExit(f"checkpoint protocol mismatch in {output}")
        if report.get("project_revision") != git_revision():
            raise SystemExit(
                f"project revision changed since {output} was created; "
                "use a new output file or return to the recorded revision"
            )
        report.setdefault("resumed_at", []).append(utc_now())
        return report
    return {
        "schema_version": 1,
        "created_at": utc_now(),
        "project_revision": git_revision(),
        "protocol": protocol,
        "machine": {
            "hostname": platform.node(),
            "cpu_model": cpu_model(),
            "platform": platform.platform(),
            "python": sys.version,
            "cpu_affinity": affinity,
            "load_average_at_start": list(os.getloadavg()),
        },
        "solver_inventory": solver_inventory(),
        "runs": [],
    }


def run_identity(run: dict) -> tuple:
    """Stable identity for importing independently measured suite rows."""
    fields = (
        "suite",
        "family",
        "case",
        "portfolio",
        "branch",
        "engine",
        "split",
        "seed",
        "repeat",
    )
    return tuple(run.get(field) for field in fields)


def import_checkpoint(report: dict, output: Path, source_path: Path) -> None:
    """Import non-error rows from a compatible per-domain checkpoint."""
    if not source_path.is_file():
        print(f"import checkpoint not present; continuing without it: {source_path}")
        return
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if source.get("project_revision") != report.get("project_revision"):
        raise SystemExit(
            f"import checkpoint revision mismatch in {source_path}: "
            f"{source.get('project_revision')} != {report.get('project_revision')}"
        )
    if source.get("machine", {}).get("hostname") != report.get("machine", {}).get(
        "hostname"
    ):
        raise SystemExit(f"import checkpoint came from another host: {source_path}")
    source_protocol = source.get("protocol", {})
    target_protocol = report["protocol"]
    for field in (
        "external_prepared_manifest_sha256",
        "external_tsp_sha256",
        "external_hcp_sha256",
    ):
        source_value = source_protocol.get(field)
        if source_value is not None and source_value != target_protocol.get(field):
            raise SystemExit(
                f"import checkpoint {field} mismatch in {source_path}: "
                f"{source_value} != {target_protocol.get(field)}"
            )
    if bool(source_protocol.get("smoke")) != bool(target_protocol.get("smoke")):
        raise SystemExit(f"import checkpoint smoke-mode mismatch in {source_path}")

    allowed_suites = set(target_protocol["suites"])
    known = {run_identity(run) for run in report["runs"]}
    affinity = source.get("machine", {}).get("cpu_affinity")
    imported = 0
    for source_run in source.get("runs", []):
        if source_run.get("status") == "ERROR":
            continue
        if source_run.get("suite") not in allowed_suites:
            continue
        identity = run_identity(source_run)
        if identity in known:
            continue
        run = dict(source_run)
        run["measurement_cpu_affinity"] = affinity
        run["imported_from"] = str(source_path)
        report["runs"].append(run)
        known.add(identity)
        imported += 1
    report.setdefault("imported_checkpoints", []).append(
        {
            "path": str(source_path),
            "source_cpu_affinity": affinity,
            "source_created_at": source.get("created_at"),
            "source_completed_at": source.get("completed_at"),
            "rows_added": imported,
            "imported_at": utc_now(),
        }
    )
    atomic_json(output, report)
    print(f"imported {imported} rows from {source_path}", flush=True)


def run_sat(
    report: dict,
    output: Path,
    repeats: int,
    cap: float,
    randomsearch_dir: Path | None,
    *,
    smoke: bool,
) -> None:
    done = {
        (run["case"], run["portfolio"], run["branch"], run["repeat"])
        for run in report["runs"]
        if run.get("suite") == "sat" and run.get("status") != "ERROR"
    }
    cases = sat_cases(randomsearch_dir)
    if smoke:
        cases = cases[:1]
        repeats = 1
    for case in cases:
        for branch in branch_names(case["portfolio"], include_context=(case["portfolio"] == "original3")):
            for repeat in range(repeats):
                key = (case["id"], case["portfolio"], branch, repeat)
                if key in done:
                    continue
                measured = measure_sat_with_timeout(branch, case["path"], case["portfolio"], cap)
                report["runs"].append(
                    {
                        "suite": "sat",
                        "case": case["id"],
                        "source": str(case["path"]),
                        "source_sha256": sha256(case["path"]),
                        "portfolio": case["portfolio"],
                        "branch": branch,
                        "repeat": repeat,
                        **measured,
                    }
                )
                atomic_json(output, report)
                if measured["status"] == "ERROR":
                    raise RuntimeError(
                        f"SAT worker failed for {case['id']}/{branch}: "
                        f"{measured.get('error')}"
                    )
                print(f"sat {case['id']} {branch} repeat={repeat}: {measured['status']}", flush=True)


def run_sat_external(
    report: dict,
    output: Path,
    external_dir: Path,
    repeats: int,
    cap: float,
    *,
    smoke: bool,
) -> None:
    paths = sorted((external_dir / "instances/sat").glob("*.cnf"))
    if not paths:
        raise FileNotFoundError(f"no prepared SAT families under {external_dir}")
    if smoke:
        paths = paths[:1]
        repeats = 1
        cap = min(cap, 1.0)
    done = {
        (run["case"], run["branch"], run["repeat"])
        for run in report["runs"]
        if run.get("suite") == "sat_external" and run.get("status") != "ERROR"
    }
    for path in paths:
        for branch in branch_names("original3", include_context=True):
            for repeat in range(repeats):
                key = (path.stem, branch, repeat)
                if key in done:
                    continue
                measured = measure_sat_with_timeout(branch, path, "original3", cap)
                report["runs"].append(
                    {
                        "suite": "sat_external",
                        "case": path.stem,
                        "family": "known_sat",
                        "source": str(path),
                        "source_sha256": sha256(path),
                        "portfolio": "original3",
                        "branch": branch,
                        "repeat": repeat,
                        **measured,
                    }
                )
                atomic_json(output, report)
                if measured["status"] == "ERROR":
                    raise RuntimeError(
                        f"SAT worker failed for {path.stem}/{branch}: "
                        f"{measured.get('error')}"
                    )
                print(
                    f"sat_external {path.stem} {branch} repeat={repeat}: "
                    f"{measured['status']}",
                    flush=True,
                )


def run_concorde_suite(
    report: dict,
    output: Path,
    suite: str,
    train_repeats: int,
    heldout_repeats: int,
    *,
    smoke: bool,
) -> None:
    if suite == "tsp":
        cases = TSP_CASES
        kind = "tsp_generated"
    else:
        cases = HAM_CASES
        kind = "ham"
    done = {
        (run["case"], run["split"], run["seed"], run["repeat"])
        for run in report["runs"]
        if run.get("suite") == suite and run.get("status") != "ERROR"
    }
    selected_cases = list(cases.items())
    if smoke:
        selected_cases = selected_cases[:1]
        train_repeats = 1
        heldout_repeats = 1
    cap = 1.0 if smoke else 60.0
    for case, relative in selected_cases:
        path = REPOSITORY / relative
        for split, seeds, repeats in (
            ("train", (1,) if smoke else range(1, 8), train_repeats),
            ("heldout", (8,) if smoke else range(8, 31), heldout_repeats),
        ):
            for seed in seeds:
                for repeat in range(repeats):
                    key = (case, split, seed, repeat)
                    if key in done:
                        continue
                    measured = measure_concorde_with_timeout(kind, path, seed, cap)
                    report["runs"].append(
                        {
                            "suite": suite,
                            "case": case,
                            "source": str(path),
                            "source_sha256": sha256(path),
                            "split": split,
                            "seed": seed,
                            "repeat": repeat,
                            **measured,
                        }
                    )
                    atomic_json(output, report)
                    if measured["status"] == "ERROR":
                        raise RuntimeError(
                            f"Concorde failed for {suite}/{case}: {measured.get('error')}"
                        )
                    print(
                        f"{suite} {case} {split} seed={seed} rep={repeat}: "
                        f"{measured['status']} {measured['cpu_time_s']:.6f}s",
                        flush=True,
                    )


def run_tsp_external(
    report: dict,
    output: Path,
    external_dir: Path,
    *,
    smoke: bool,
) -> None:
    cases = []
    for family in ("tsplib", "hard_tsplib", "clustered_euclidean"):
        paths = sorted((external_dir / "instances" / family).glob("*.tsp"))
        if not paths:
            raise FileNotFoundError(f"no prepared {family} instances under {external_dir}")
        if smoke and family == "tsplib":
            selected = [next(path for path in paths if path.name == "gr229.tsp")]
        elif smoke and family == "hard_tsplib":
            selected = [next(path for path in paths if path.name == "20009_hard.tsp")]
        else:
            selected = paths[:1] if smoke else paths
        cases.extend((family, path) for path in selected)
    done = {
        (run["family"], run["case"], run["split"], run["seed"], run["repeat"])
        for run in report["runs"]
        if run.get("suite") == "tsp_external" and run.get("status") != "ERROR"
    }
    cap = 1.0 if smoke else 60.0
    for family, path in cases:
        plans = [("train", tuple(range(1, 2) if smoke else range(1, 8)))]
        if path.name in ("gr229.tsp", "20009_hard.tsp"):
            plans.append(
                ("heldout", tuple(range(8, 9) if smoke else range(8, 31)))
            )
        for split, seeds in plans:
            required_timeouts = len(seeds) // 2 + 1
            for seed in seeds:
                timeout_seeds = {
                    run["seed"]
                    for run in report["runs"]
                    if run.get("suite") == "tsp_external"
                    and run.get("family") == family
                    and run.get("case") == path.stem
                    and run.get("split") == split
                    and run.get("status") == "TIMEOUT"
                }
                if len(timeout_seeds) >= required_timeouts:
                    print(
                        f"tsp_external {family}/{path.stem} {split}: median is "
                        f"right-censored at {cap:g}s after "
                        f"{len(timeout_seeds)}/{len(seeds)} timeout seeds",
                        flush=True,
                    )
                    break
                repeat = 0
                key = (family, path.stem, split, seed, repeat)
                if key in done:
                    continue
                measured = measure_concorde_with_timeout(
                    "tsp_native", path, seed, cap
                )
                report["runs"].append(
                    {
                        "suite": "tsp_external",
                        "family": family,
                        "case": path.stem,
                        "source": str(path),
                        "source_sha256": sha256(path),
                        "split": split,
                        "seed": seed,
                        "repeat": repeat,
                        **measured,
                    }
                )
                atomic_json(output, report)
                if measured["status"] == "ERROR":
                    raise RuntimeError(
                        f"Concorde failed for {family}/{path.stem}: "
                        f"{measured.get('error')}"
                    )
                print(
                    f"tsp_external {family}/{path.stem} {split} seed={seed}: "
                    f"{measured['status']} {measured['cpu_time_s']:.6f}s",
                    flush=True,
                )


def run_ham_external(
    report: dict,
    output: Path,
    external_dir: Path,
    *,
    smoke: bool,
) -> None:
    paths = sorted(
        (external_dir / "instances/fhcp").glob("*.hcp"),
        key=lambda path: int(path.stem.removeprefix("graph")),
    )
    if not paths:
        raise FileNotFoundError(f"no prepared FHCP instances under {external_dir}")
    if smoke:
        paths = paths[:1]
    done = {
        (run["case"], run["seed"], run["repeat"])
        for run in report["runs"]
        if run.get("suite") == "ham_external" and run.get("status") != "ERROR"
    }
    cap = 1.0 if smoke else 60.0
    for path in paths:
        seeds = tuple(range(1, 2) if smoke else range(1, 8))
        required_timeouts = len(seeds) // 2 + 1
        for seed in seeds:
            timeout_seeds = {
                run["seed"]
                for run in report["runs"]
                if run.get("suite") == "ham_external"
                and run.get("case") == path.stem
                and run.get("split") == "train"
                and run.get("status") == "TIMEOUT"
            }
            if len(timeout_seeds) >= required_timeouts:
                print(
                    f"ham_external fhcp/{path.stem}: median is right-censored "
                    f"at {cap:g}s after {len(timeout_seeds)}/{len(seeds)} "
                    "timeout seeds",
                    flush=True,
                )
                break
            repeat = 0
            key = (path.stem, seed, repeat)
            if key in done:
                continue
            measured = measure_concorde_with_timeout("ham", path, seed, cap)
            report["runs"].append(
                {
                    "suite": "ham_external",
                    "family": "fhcp",
                    "case": path.stem,
                    "source": str(path),
                    "source_sha256": sha256(path),
                    "split": "train",
                    "seed": seed,
                    "repeat": repeat,
                    **measured,
                }
            )
            atomic_json(output, report)
            if measured["status"] == "ERROR":
                raise RuntimeError(
                    f"Concorde failed for fhcp/{path.stem}: {measured.get('error')}"
                )
            print(
                f"ham_external fhcp/{path.stem} seed={seed}: "
                f"{measured['status']} {measured['cpu_time_s']:.6f}s",
                flush=True,
            )


def solve_cpsat(matrix: list[list[int]], seed: int, cap: float) -> dict:
    from ortools.sat.python import cp_model

    n_jobs, n_machines = len(matrix), len(matrix[0])
    model = cp_model.CpModel()
    horizon = sum(sum(row) for row in matrix)
    starts, ends, intervals = {}, {}, {}
    for job in range(n_jobs):
        for machine in range(n_machines):
            duration = int(matrix[job][machine])
            start = model.new_int_var(0, horizon, f"s_{job}_{machine}")
            end = model.new_int_var(0, horizon, f"e_{job}_{machine}")
            interval = model.new_interval_var(start, duration, end, f"i_{job}_{machine}")
            starts[job, machine] = start
            ends[job, machine] = end
            intervals[job, machine] = interval
    for job in range(n_jobs):
        for machine in range(n_machines - 1):
            model.add(ends[job, machine] <= starts[job, machine + 1])
    for machine in range(n_machines):
        model.add_no_overlap([intervals[job, machine] for job in range(n_jobs)])
    makespan = model.new_int_var(0, horizon, "makespan")
    model.add_max_equality(makespan, [ends[job, n_machines - 1] for job in range(n_jobs)])
    model.minimize(makespan)
    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = seed
    solver.parameters.max_time_in_seconds = cap
    start = time.process_time()
    status_code = solver.solve(model)
    elapsed = time.process_time() - start
    return {
        "status": solver.status_name(status_code),
        "cpu_time_s": elapsed,
        "objective_value": solver.objective_value if status_code in (cp_model.OPTIMAL, cp_model.FEASIBLE) else None,
        "best_objective_bound": solver.best_objective_bound,
    }


def run_npfs(report: dict, output: Path, *, smoke: bool) -> None:
    cpopt = load_module(
        REPOSITORY / "comparisons/vrf_cpopt_10x5/run_cpopt.py", "paper_cpopt_runner"
    )
    import docplex.cp.config as cpconfig

    cpopt_executable = cpopt.find_cpoptimizer()
    cpconfig.context.solver.local.execfile = cpopt_executable
    cpconfig.context.solver.local.process_start_timeout = 60
    report["solver_inventory"]["cpoptimizer"] = {
        "path": cpopt_executable,
        "sha256": sha256(Path(cpopt_executable)),
    }
    done = {
        (run["case"], run["engine"], run["split"], run["seed"])
        for run in report["runs"]
        if run.get("suite") == "npfs"
    }
    selected_cases = list(NPFS_CASES.items())
    if smoke:
        selected_cases = selected_cases[:1]
    for case, specification in selected_cases:
        path = REPOSITORY / specification["path"]
        matrix = parse_npfs(path)
        plan = [
            (engine, "train", (1,) if smoke else range(1, 8))
            for engine in specification["train_engines"]
        ]
        if specification["heldout"]:
            plan.append(
                (specification["own_engine"], "heldout", (8,) if smoke else range(8, 31))
            )
        for engine, split, seeds in plan:
            for seed in seeds:
                key = (case, engine, split, seed)
                if key in done:
                    continue
                if engine == "cpsat":
                    measured = solve_cpsat(matrix, seed, specification["cap"])
                else:
                    measured = cpopt.solve(matrix, seed, specification["cap"])
                report["runs"].append(
                    {
                        "suite": "npfs",
                        "case": case,
                        "source": str(path),
                        "source_sha256": sha256(path),
                        "engine": engine,
                        "split": split,
                        "seed": seed,
                        "cap_s": specification["cap"],
                        **measured,
                    }
                )
                atomic_json(output, report)
                print(
                    f"npfs {case} {engine} {split} seed={seed}: "
                    f"{measured['status']} {measured['cpu_time_s']:.6f}s",
                    flush=True,
                )


def geometric_mean(values: list[float]) -> float:
    return math.exp(sum(math.log(value) for value in values) / len(values))


def summarize(report: dict) -> dict:
    summary: dict = {
        "sat": {},
        "sat_external": {},
        "tsp": {},
        "tsp_external": {},
        "ham": {},
        "ham_external": {},
        "npfs": {},
    }
    for suite in ("sat", "sat_external"):
        sat_runs = [
            run
            for run in report["runs"]
            if run.get("suite") == suite and run.get("status") != "ERROR"
        ]
        for case in sorted({run["case"] for run in sat_runs}):
            case_runs = [run for run in sat_runs if run["case"] == case]
            portfolio = case_runs[0]["portfolio"]
            branches = {}
            for branch in sorted({run["branch"] for run in case_runs}):
                values = [
                    float(run["charged_cpu_s"])
                    for run in case_runs
                    if run["branch"] == branch
                ]
                branches[branch] = {
                    "times_s": values,
                    "median_s": statistics.median(values),
                }
            by_repeat = {}
            for run in case_runs:
                if run["branch"] in portfolio_members(portfolio):
                    by_repeat.setdefault(run["repeat"], []).append(
                        float(run["charged_cpu_s"])
                    )
            minima = [min(values) for _, values in sorted(by_repeat.items())]
            summary[suite][case] = {
                "portfolio": portfolio,
                "virtual_best_runs_s": minima,
                "virtual_best_median_s": statistics.median(minima),
                "branches": branches,
            }
    for suite in ("tsp", "ham"):
        suite_runs = [
            run
            for run in report["runs"]
            if run.get("suite") == suite and run.get("status") != "ERROR"
        ]
        for case in sorted({run["case"] for run in suite_runs}):
            result = {}
            for split in ("train", "heldout"):
                split_runs = [run for run in suite_runs if run["case"] == case and run["split"] == split]
                seed_values = []
                for seed in sorted({run["seed"] for run in split_runs}):
                    repetitions = [run["cpu_time_s"] for run in split_runs if run["seed"] == seed]
                    seed_values.append(geometric_mean(repetitions))
                if seed_values:
                    result[split] = {
                        "seed_values_s": seed_values,
                        "median_s": statistics.median(seed_values),
                        "geomean_s": geometric_mean(seed_values),
                    }
            summary[suite][case] = result
    for suite in ("tsp_external", "ham_external"):
        suite_runs = [
            run
            for run in report["runs"]
            if run.get("suite") == suite and run.get("status") != "ERROR"
        ]
        case_results = {}
        for case in sorted({run["case"] for run in suite_runs}):
            case_runs = [run for run in suite_runs if run["case"] == case]
            result = {"family": case_runs[0]["family"]}
            for split in ("train", "heldout"):
                split_runs = [run for run in case_runs if run["split"] == split]
                seed_values = []
                for seed in sorted({run["seed"] for run in split_runs}):
                    repetitions = [
                        float(run["cpu_time_s"])
                        for run in split_runs
                        if run["seed"] == seed
                    ]
                    seed_values.append(geometric_mean(repetitions))
                if seed_values:
                    timeout_seed_count = len(
                        {
                            run["seed"]
                            for run in split_runs
                            if run["status"] == "TIMEOUT"
                        }
                    )
                    planned_seed_count = (
                        1
                        if report["protocol"]["smoke"]
                        else (7 if split == "train" else 23)
                    )
                    required_timeout_count = planned_seed_count // 2 + 1
                    split_result = {
                        "seed_values_s": seed_values,
                        "median_s": statistics.median(seed_values),
                        "observed_seed_count": len(seed_values),
                        "planned_seed_count": planned_seed_count,
                        "timeout_seed_count": timeout_seed_count,
                        "required_timeout_count_for_median_censor": (
                            required_timeout_count
                        ),
                    }
                    if timeout_seed_count >= required_timeout_count:
                        split_result["median_right_censored_at_s"] = max(
                            float(run["cap_s"]) for run in split_runs
                        )
                    else:
                        split_result["geomean_s"] = geometric_mean(seed_values)
                    result[split] = split_result
            case_results[case] = result
        families = {}
        for family in sorted({run["family"] for run in suite_runs}):
            family_cases = {
                case: result
                for case, result in case_results.items()
                if result["family"] == family and "train" in result
            }
            medians = {
                case: float(result["train"]["median_s"])
                for case, result in family_cases.items()
            }
            if not medians:
                continue
            cap = max(
                float(run["cap_s"])
                for run in suite_runs
                if run["family"] == family
            )
            solved = {case: value for case, value in medians.items() if value < cap}
            families[family] = {
                "case_count": len(medians),
                "median_of_case_medians_s": statistics.median(medians.values()),
                "capped_cases": sorted(case for case, value in medians.items() if value >= cap),
                "slowest_solved_train_case": (
                    None
                    if not solved
                    else max(solved.items(), key=lambda item: item[1])
                ),
            }
        summary[suite] = {"cases": case_results, "families": families}
    npfs_runs = [run for run in report["runs"] if run.get("suite") == "npfs"]
    for case in sorted({run["case"] for run in npfs_runs}):
        result = {}
        for engine in sorted({run["engine"] for run in npfs_runs if run["case"] == case}):
            for split in ("train", "heldout"):
                runs = [
                    run for run in npfs_runs
                    if run["case"] == case and run["engine"] == engine and run["split"] == split
                ]
                if runs:
                    values = [float(run["cpu_time_s"]) for run in runs]
                    result[f"{engine}_{split}"] = {
                        "times_s": values,
                        "median_s": statistics.median(values),
                        "geomean_s": geometric_mean(values),
                        "statuses": [run["status"] for run in runs],
                    }
        summary["npfs"][case] = result
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        action="append",
        choices=(
            "sat",
            "sat_external",
            "tsp",
            "tsp_external",
            "ham",
            "ham_external",
            "npfs",
        ),
        help="repeat to select suites; default is all",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--randomsearch-dir", type=Path)
    parser.add_argument("--external-dir", type=Path)
    parser.add_argument(
        "--import-checkpoint",
        action="append",
        type=Path,
        default=[],
        help="compatible per-domain checkpoint whose completed rows are prefilled",
    )
    parser.add_argument("--sat-repeats", type=int, default=5)
    parser.add_argument("--sat-cap", type=float, default=60.0)
    parser.add_argument("--concorde-train-repeats", type=int, default=3)
    parser.add_argument("--concorde-heldout-repeats", type=int, default=1)
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="run one small case/seed per selected suite for dependency validation",
    )
    args = parser.parse_args()
    default_suites = ["sat", "tsp", "ham", "npfs"]
    if args.external_dir is not None:
        default_suites.extend(("sat_external", "tsp_external", "ham_external"))
    suites = args.suite or default_suites
    external_suites = {"sat_external", "tsp_external", "ham_external"}
    if external_suites.intersection(suites) and args.external_dir is None:
        parser.error("--external-dir is required for external suites")
    external_dir = None if args.external_dir is None else args.external_dir.resolve()
    external_metadata = (
        validate_external_inputs(external_dir)
        if external_dir is not None and external_suites.intersection(suites)
        else None
    )
    affinity = assert_single_cpu()
    output = args.output.resolve()
    protocol = {
        "suites": suites,
        "sat_repeats": args.sat_repeats,
        "sat_cap_s": args.sat_cap,
        "concorde_train_repeats": args.concorde_train_repeats,
        "concorde_heldout_repeats": args.concorde_heldout_repeats,
        "external_concorde_repeats_per_seed": 1,
        "external_concorde_censor_rule": (
            "one solve per seed; stop after a strict majority of planned seeds "
            "time out, which proves that the seeded median is right-censored "
            "at the process-CPU cap"
        ),
        "import_checkpoints": [
            str(path.resolve()) for path in args.import_checkpoint
        ],
        "randomsearch_dir": (
            None if args.randomsearch_dir is None else str(args.randomsearch_dir.resolve())
        ),
        "randomsearch_candidates_sha256": directory_digest(
            None if args.randomsearch_dir is None else args.randomsearch_dir.resolve(),
            "*.cnf",
        ),
        "external_dir": None if external_dir is None else str(external_dir),
        "external_prepared_manifest_sha256": (
            None if external_metadata is None else external_metadata["manifest_sha256"]
        ),
        "external_family_counts": (
            None if external_metadata is None else external_metadata["family_counts"]
        ),
        "external_cnf_sha256": directory_digest(external_dir, "*.cnf")
        if external_dir is not None
        else None,
        "external_tsp_sha256": directory_digest(external_dir, "*.tsp")
        if external_dir is not None
        else None,
        "external_hcp_sha256": directory_digest(external_dir, "*.hcp")
        if external_dir is not None
        else None,
        "smoke": args.smoke,
        "execution": "serial, one logical CPU, one solver branch at a time",
    }
    report = make_report(output, affinity, protocol)
    for source_path in args.import_checkpoint:
        import_checkpoint(report, output, source_path.resolve())
    if "sat" in suites:
        run_sat(
            report,
            output,
            args.sat_repeats,
            args.sat_cap,
            args.randomsearch_dir,
            smoke=args.smoke,
        )
    if "tsp" in suites:
        run_concorde_suite(
            report,
            output,
            "tsp",
            args.concorde_train_repeats,
            args.concorde_heldout_repeats,
            smoke=args.smoke,
        )
    if "ham" in suites:
        run_concorde_suite(
            report,
            output,
            "ham",
            args.concorde_train_repeats,
            args.concorde_heldout_repeats,
            smoke=args.smoke,
        )
    if "npfs" in suites:
        run_npfs(report, output, smoke=args.smoke)
    if "sat_external" in suites:
        run_sat_external(
            report,
            output,
            external_dir,
            args.sat_repeats,
            args.sat_cap,
            smoke=args.smoke,
        )
    if "tsp_external" in suites:
        run_tsp_external(
            report,
            output,
            external_dir,
            smoke=args.smoke,
        )
    if "ham_external" in suites:
        run_ham_external(
            report,
            output,
            external_dir,
            smoke=args.smoke,
        )
    report["summary"] = summarize(report)
    report["completed_at"] = utc_now()
    atomic_json(output, report)
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
