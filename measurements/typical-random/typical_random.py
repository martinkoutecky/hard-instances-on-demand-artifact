#!/usr/bin/env python3
"""Typical-random hardness statistics for the ALENEX paper.

Measures the MEDIAN portfolio/engine CPU time of N fresh uniform draws
from the paper's own encodings, on the reference machine, pinned to one
logical CPU -- the defined statistic behind the "typical random instance"
sentences. One evaluation per draw; the median over N draws is robust to
per-solve noise.

- SAT: kcnf encoding (200 vars, 1000 clauses), Nevergrad parametrization
  sampler (same as the RandomSearch campaign), portfolio original3
  virtual-best minimum.
- NPFS: uniform integer duration matrices in [1,100], CP Optimizer,
  solver seed 1, sizes 8x4 and 10x5.

Sampling seed 20260719 (independent of the campaign master seed).
Usage: taskset -c <cpu> python3 typical_random.py {sat|npfs8|npfs10}
"""
import json, os, statistics, sys, time
from pathlib import Path

for v in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS","BLIS_NUM_THREADS"):
    os.environ[v] = "1"

REBENCH = Path(__file__).resolve().parents[2] / 'current_machine_rebench'
REPO = REBENCH.parent
OUT = Path(__file__).resolve().parent
N = 1000
SEED = 20260719
CAP = 60.0

affinity = sorted(os.sched_getaffinity(0))
assert len(affinity) == 1, f"pin to one CPU first, got {affinity}"

def report(name, times, extra):
    times_sorted = sorted(times)
    rec = {
        "statistic": "median CPU time of N fresh uniform draws, one evaluation per draw",
        "n_draws": len(times), "seed": SEED, "cap_s": CAP,
        "median_s": statistics.median(times),
        "q1_s": times_sorted[len(times)//4], "q3_s": times_sorted[3*len(times)//4],
        "max_s": times_sorted[-1], "cpu_affinity": affinity, **extra,
    }
    (OUT / f"{name}.json").write_text(json.dumps(rec, indent=1) + "\n")
    print(name, "median", rec["median_s"], "q1", rec["q1_s"], "q3", rec["q3_s"], "max", rec["max_s"])

mode = sys.argv[1]
if mode == "sat":
    sys.path.insert(0, str(REBENCH)); sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO/"SAT"))
    from ng_class import My_Test
    from sat_common import branch_names, measure_branch, test_to_clauses, solver_inventory
    factory = My_Test(1000, 200, encoding="kcnf", l=3)
    parameter = factory.encode()
    parameter.random_state.seed(SEED)
    times = []
    t0 = time.monotonic()
    for i in range(N):
        encoded = [int(x) for x in parameter.sample().value]
        clauses, n_vars = test_to_clauses(factory.decode_test(encoded))
        vals = [float(measure_branch(b, clauses, n_vars, CAP, portfolio="original3")["charged_cpu_s"])
                for b in branch_names("original3")]
        times.append(min(vals))
        if (i+1) % 100 == 0:
            print(f"sat {i+1}/{N} median so far {statistics.median(times):.4f} elapsed {time.monotonic()-t0:.0f}s", flush=True)
    report("sat-typical-kcnf", times, {"encoding": "kcnf", "portfolio": "original3",
                                       "solver_inventory": solver_inventory()})
elif mode in ("npfs8", "npfs10"):
    import numpy as np
    sys.path.insert(0, str(REPO/"JSSP"))
    import solution_cpopt as cpopt
    n, m = (8, 4) if mode == "npfs8" else (10, 5)
    rng = np.random.default_rng(SEED)
    times = []
    t0 = time.monotonic()
    for i in range(N):
        matrix = rng.integers(1, 101, size=(n, m), dtype=np.int64)
        times.append(min(float(cpopt.solve(matrix, n, m, seed=1, time_limit=CAP)), CAP))
        if (i+1) % 100 == 0:
            print(f"{mode} {i+1}/{N} median so far {statistics.median(times):.4f} elapsed {time.monotonic()-t0:.0f}s", flush=True)
    report(f"npfs-typical-{n}x{m}", times, {"size": f"{n}x{m}", "engine": "CP Optimizer", "solver_seed": 1})
else:
    raise SystemExit("mode must be sat | npfs8 | npfs10")
