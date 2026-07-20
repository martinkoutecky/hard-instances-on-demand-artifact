"""Shared SAT measurement helpers for the current-machine campaign.

The paper's portfolio score is a virtual-best CPU-time minimum.  These helpers
measure one branch after another so a run restricted to one logical CPU never
has several solver branches active at once.  The BreakID branch is deliberately
pinned to CaDiCaL 1.9.5; the project modules otherwise auto-select Kissat when
it is installed, which would not match the paper's labels.
"""

from __future__ import annotations

import hashlib
import os
import resource
import sys
import time
from pathlib import Path
from typing import Iterable

from pysat.solvers import Solver


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parent
SAT_DIR = REPOSITORY / "SAT"
DPLL4_DIR = REPOSITORY / "dpll4_portfolio"

for variable in (
    "OMP_NUM_THREADS",
    "MKL_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "BLIS_NUM_THREADS",
):
    os.environ.setdefault(variable, "1")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_dimacs(path: Path) -> tuple[list[list[int]], int]:
    clauses: list[list[int]] = []
    declared_vars = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("c"):
            continue
        if line.startswith("p"):
            fields = line.split()
            if len(fields) != 4 or fields[1] != "cnf":
                raise ValueError(f"bad DIMACS header in {path}: {line}")
            declared_vars = int(fields[2])
            continue
        values = [int(value) for value in line.split()]
        if not values or values[-1] != 0:
            raise ValueError(f"unterminated DIMACS clause in {path}: {line}")
        clauses.append(values[:-1])
    if not declared_vars:
        declared_vars = max((abs(lit) for clause in clauses for lit in clause), default=0)
    return clauses, declared_vars


def write_dimacs(path: Path, clauses: Iterable[Iterable[int]], n_vars: int) -> None:
    rows = [list(clause) for clause in clauses]
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        handle.write(f"p cnf {n_vars} {len(rows)}\n")
        for clause in rows:
            handle.write(" ".join(str(value) for value in clause) + " 0\n")
    temporary.replace(path)


def test_to_clauses(test: list[dict]) -> tuple[list[list[int]], int]:
    clauses: list[list[int]] = []
    n_vars = 0
    for item in test:
        clause = [int(value) for value in item["positive"]]
        clause.extend(-int(value) for value in item["negative"])
        if clause:
            clauses.append(clause)
            n_vars = max(n_vars, *(abs(value) for value in clause))
    return clauses, n_vars


def clauses_to_test(clauses: list[list[int]]) -> list[dict]:
    return [
        {
            "positive": [value for value in clause if value > 0],
            "negative": [-value for value in clause if value < 0],
        }
        for clause in clauses
    ]


def _load_original_module():
    sys.path.insert(0, str(SAT_DIR))
    try:
        import solution_portfolio as module
    finally:
        sys.path.pop(0)
    module._STRONG_CDCL = "cadical195"
    return module


def _load_dpll4_module():
    sys.path.insert(0, str(DPLL4_DIR))
    try:
        import solution_portfolio4 as module
    finally:
        sys.path.pop(0)
    module._STRONG_CDCL = "cadical195"
    return module


def _pysat(name: str, clauses: list[list[int]]) -> tuple[float, str]:
    solver = Solver(name=name, bootstrap_with=clauses)
    start = time.process_time()
    verdict = solver.solve()
    elapsed = time.process_time() - start
    solver.delete()
    return elapsed, "SAT" if verdict else "UNSAT"


def _cryptominisat(clauses: list[list[int]]) -> tuple[float, str]:
    import pycryptosat

    solver = pycryptosat.Solver(threads=1)
    for clause in clauses:
        solver.add_clause(clause)
    start = time.process_time()
    answer = solver.solve()
    elapsed = time.process_time() - start
    verdict = answer[0] if isinstance(answer, tuple) else answer
    return elapsed, "SAT" if verdict else "UNSAT"


def branch_names(portfolio: str, *, include_context: bool = False) -> tuple[str, ...]:
    if portfolio == "original3":
        names = ("minisat22", "breakid_cadical195", "cryptominisat")
        if include_context:
            names += ("kissat404", "march_cu")
        return names
    if portfolio == "dpll4":
        return ("kissat_binary", "breakid_cadical195", "cryptominisat", "march_cu")
    raise ValueError(f"unknown portfolio {portfolio!r}")


def portfolio_members(portfolio: str) -> tuple[str, ...]:
    return branch_names(portfolio, include_context=False)


def measure_branch(
    branch: str,
    clauses: list[list[int]],
    n_vars: int,
    cap: float,
    *,
    portfolio: str,
) -> dict:
    """Measure one branch; the caller supplies process-level timeout handling."""
    if branch == "minisat22":
        elapsed, status = _pysat("minisat22", clauses)
        charged = elapsed
    elif branch == "kissat404":
        elapsed, status = _pysat("kissat404", clauses)
        charged = elapsed
    elif branch == "cryptominisat":
        elapsed, status = _cryptominisat(clauses)
        charged = elapsed
    elif branch == "breakid_cadical195":
        module = _load_original_module() if portfolio == "original3" else _load_dpll4_module()
        preprocessed = module._breakid_preprocess(clauses, n_vars)
        elapsed, status = _pysat("cadical195", preprocessed)
        charged = elapsed + 0.008
    elif branch in ("kissat_binary", "march_cu"):
        module = _load_dpll4_module()
        which = "kissat" if branch == "kissat_binary" else "march"
        before = resource.getrusage(resource.RUSAGE_CHILDREN)
        elapsed = float(module._run_binary(which, clauses, n_vars, cap))
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        # _run_binary already returns the child CPU delta. Keep this fallback
        # only as diagnostic metadata in case a future implementation changes.
        observed_child_delta = (
            after.ru_utime - before.ru_utime + after.ru_stime - before.ru_stime
        )
        status = "TIMEOUT" if elapsed >= cap else "SOLVED"
        charged = elapsed
        return {
            "branch": branch,
            "raw_cpu_s": min(elapsed, cap),
            "charged_cpu_s": min(charged, cap),
            "status": status,
            "child_cpu_delta_s": observed_child_delta,
        }
    else:
        raise ValueError(f"unknown SAT branch {branch!r}")
    return {
        "branch": branch,
        "raw_cpu_s": min(float(elapsed), cap),
        "charged_cpu_s": min(float(charged), cap),
        "status": "TIMEOUT" if elapsed >= cap else status,
    }


def solver_inventory() -> dict:
    import importlib.metadata

    dpll = _load_dpll4_module()
    original = _load_original_module()
    binaries = {
        "breakid_original": SAT_DIR / "breakid",
        "breakid_dpll4": DPLL4_DIR / "bin" / "breakid",
        "kissat": DPLL4_DIR / "bin" / "kissat",
        "march_cu": DPLL4_DIR / "bin" / "march_cu",
    }
    return {
        "pinned_strong_cdcl": "cadical195",
        "python_sat": importlib.metadata.version("python-sat"),
        "pycryptosat": importlib.metadata.version("pycryptosat"),
        "original_active_guards_after_pin": original.active_guards(),
        "dpll4_active_guards_after_pin": dpll.active_guards(),
        "binaries": {
            name: {"path": str(path), "sha256": sha256(path)}
            for name, path in binaries.items()
        },
    }
