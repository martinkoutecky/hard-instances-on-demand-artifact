# DPLL 4-solver portfolio run (`dpll4f`)

A self-contained, distinguishable package for the **paradigm-robust** SAT
experiment: instances bred to be hard for a **four-solver, paradigm-diverse**
portfolio, together with the exact configs that were run and a runnable copy of
the objective.

## Why this run exists

The main-paper SAT champions (`champions/sat/champ_*_gt1s2L.cnf`) are hard for
the three-branch **CDCL** portfolio, but a look-ahead/DPLL solver cracks them
quickly — `march_cu` solves them in ~0.44–0.68 s. Hardness there is
*solver-class-relative*. This run answers the obvious critique by adding a
**fourth, non-CDCL branch** and breeding against the minimum of all four:

| branch | solver | paradigm it guards against being easy |
|---|---|---|
| 1 | `kissat` | strongest CDCL baseline (replaces minisat22) |
| 2 | BreakID → `cadical195` | symmetry (e.g. pigeonhole) |
| 3 | CryptoMiniSat | XOR / parity |
| 4 | **`march_cu -p`** | **complete look-ahead / DPLL** |

Hardness = `min` over the four branches (process CPU time, 120 s per-branch cap,
BreakID charged a flat 8 ms as in the main portfolio). An instance is only hard
if **every** paradigm is slow on it.

## Result

All four champions are **UNSAT** and take **~1.2–1.5 s** under the four-solver
minimum — i.e. they stay hard even for the DPLL branch. Re-solving each committed
CNF here reproduces its recorded value (deterministic; process-time based):

| instance | v/c | optimizer | recorded | re-solve | ratio |
|---|---|---|---:|---:|---:|
| `instances/champ4_mpfx_log.cnf` (headline) | 200/962 | TripleCMA | 1.466 s | 1.450 s | 0.99× |
| `instances/champ4_kcnf_log.cnf` | 200/1000 | TripleCMA | 1.386 s | 1.385 s | 1.00× |
| `instances/champ4_mpfx_neg.cnf` | 200/884 | MultiScaleCMA | 1.199 s | 1.228 s | 1.02× |
| `instances/champ4_kcnf_neg.cnf` | 200/1000 | TripleCMA | 1.179 s | 1.215 s | 1.03× |

(Recorded = `.rebench_bg/SAT_dpll4f` clean local rebench, k=5 reps=5.)

## Layout

~~~text
dpll4_portfolio/
  instances/   champ4_{kcnf,mpfx}_{log,neg}.cnf   # the 4 bred champions (DIMACS)
  configs/     config_dpll4f_sat_{kcnf,mpfx}_{log,neg}.json   # the configs that ran
  solution_portfolio4.py    # the 4-solver objective (min over the branches)
  bin/         kissat  march_cu  breakid  libbreakid.so{,.3.1}   # bundled solvers
  manifest.json
~~~

The configs are Stage-2 scale: `N=1000` clause slots, `Var=200`, budget 100,000,
5 iters, `require_full_portfolio=true`, per-candidate objective = median of 3.
One champion is the arg-max instance of each config's archive cell (provenance —
config / optimizer / iter / idx — is in `manifest.json`).

## Running

`solution_portfolio4.py` is the working-repo module (it lived in `SAT/`), copied
here verbatim except that its solver paths were repointed from
`SAT_BENCHMARK/tools/` to this directory's `bin/`. It needs, in addition to the
bundled binaries, `python-sat` (provides `cadical195` for branch 2) and
`pycryptosat` (branch 3):

~~~python
import solution_portfolio4 as P4
cnf = [{"positive": [...], "negative": [...]}, ...]   # or parse a DIMACS file
seconds = P4.solve(cnf)     # min CPU time over the four branches
~~~

## Provenance

Instances are the committed `sat_champ4_*.cnf` from the working repo; configs are
`SAT/config_dpll4f_sat_*.json` (the `--code dpll4f` run, archive
`SAT/logs_arch_dpll4f`). Excluded from the minimal thesis attachment on purpose;
included here as ALENEX evidence that the generator's hardness is not merely a
CDCL artifact.
