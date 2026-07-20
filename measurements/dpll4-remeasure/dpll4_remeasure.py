#!/usr/bin/env python3
"""Reference-machine remeasurement of the 4-solver (dpll4f) SAT champions.

Champions bred against min over {kissat, BreakID->cadical195, CryptoMiniSat,
march_cu -p} (dpll4_portfolio/, Stage-2 scale, budget 100k). This script
re-measures them on the reference machine under the paper's final-table
protocol: each branch measured separately, sequentially, pinned to one
logical CPU, median of five evaluations per branch, cap 60 s. Portfolio
hardness = min over the four branch medians.

"typical" mode: the SAME 1000 fresh uniform kcnf draws as the original3
typical-random statistic (sampler seed 20260719), evaluated once per branch
under the dpll4 portfolio; per-draw hardness = min over branches.

Usage: taskset -c <cpu> python3 dpll4_remeasure.py {champs|typical}
"""
import json, os, statistics, sys, time
from pathlib import Path

for v in ("OMP_NUM_THREADS","MKL_NUM_THREADS","OPENBLAS_NUM_THREADS","BLIS_NUM_THREADS"):
    os.environ[v] = "1"

REBENCH = Path(__file__).resolve().parents[2] / 'current_machine_rebench'
REPO = REBENCH.parent
DPLL4 = REPO / "dpll4_portfolio"
OUT = Path(__file__).resolve().parent
CAP = 60.0
REPS = 5
N = 1000
SEED = 20260719

affinity = sorted(os.sched_getaffinity(0))
assert len(affinity) == 1, f"pin to one CPU first, got {affinity}"

sys.path.insert(0, str(REBENCH)); sys.path.insert(0, str(REPO)); sys.path.insert(0, str(REPO/"SAT"))
from sat_common import branch_names, measure_branch, solver_inventory
from run_rebench import measure_sat_with_timeout

BRANCHES = branch_names("dpll4")

mode = sys.argv[1]
if mode == "champs":
    champs = sorted((DPLL4 / "instances").glob("champ4_*.cnf"))
    assert len(champs) == 4, champs
    results = {}
    t0 = time.monotonic()
    for path in champs:
        per_branch = {}
        for b in BRANCHES:
            vals, statuses = [], []
            for r in range(REPS):
                m = measure_sat_with_timeout(b, path, "dpll4", CAP)
                vals.append(float(m["charged_cpu_s"]))
                statuses.append(m["status"])
                print(f"{path.name} {b} rep{r+1} {vals[-1]:.3f}s {statuses[-1]}", flush=True)
            per_branch[b] = {"median_s": statistics.median(vals), "all_s": vals,
                             "statuses": statuses}
        pmin = min(v["median_s"] for v in per_branch.values())
        results[path.name] = {"branches": per_branch, "portfolio_min_s": pmin}
        print(f"== {path.name} portfolio min {pmin:.3f}s elapsed {time.monotonic()-t0:.0f}s", flush=True)
    (OUT / "dpll4-champions.json").write_text(json.dumps({
        "protocol": "per-branch median of 5 sequential evaluations, cap 60 s, "
                    "portfolio min over branch medians",
        "portfolio": "dpll4", "branches": list(BRANCHES),
        "cpu_affinity": affinity, "results": results,
        "solver_inventory": solver_inventory(),
    }, indent=1) + "\n")
elif mode == "typical":
    from ng_class import My_Test
    from sat_common import test_to_clauses
    factory = My_Test(1000, 200, encoding="kcnf", l=3)
    parameter = factory.encode()
    parameter.random_state.seed(SEED)
    times = []
    t0 = time.monotonic()
    for i in range(N):
        encoded = [int(x) for x in parameter.sample().value]
        clauses, n_vars = test_to_clauses(factory.decode_test(encoded))
        vals = [float(measure_branch(b, clauses, n_vars, CAP, portfolio="dpll4")["charged_cpu_s"])
                for b in BRANCHES]
        times.append(min(vals))
        if (i+1) % 100 == 0:
            print(f"typical {i+1}/{N} median so far {statistics.median(times):.4f} elapsed {time.monotonic()-t0:.0f}s", flush=True)
    ts = sorted(times)
    (OUT / "dpll4-typical-kcnf.json").write_text(json.dumps({
        "statistic": "median dpll4-portfolio-min CPU time of N fresh uniform kcnf draws, "
                     "one evaluation per branch per draw",
        "n_draws": N, "seed": SEED, "cap_s": CAP,
        "median_s": statistics.median(times),
        "q1_s": ts[len(ts)//4], "q3_s": ts[3*len(ts)//4], "max_s": ts[-1],
        "cpu_affinity": affinity, "portfolio": "dpll4",
        "solver_inventory": solver_inventory(),
    }, indent=1) + "\n")
    print("typical median", statistics.median(times), "max", ts[-1])
else:
    raise SystemExit("mode must be champs | typical")
