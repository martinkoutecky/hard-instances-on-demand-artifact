# Reconstructed TODO instances

The "missing selected instances" from [`../todo/MISSING_INSTANCES.md`](../todo/MISSING_INSTANCES.md)
(which mirrors [`../ALENEX_MANIFEST.md`](../ALENEX_MANIFEST.md) §4), rebuilt here
as immutable native files. Each was either regenerated from its documented
winner-seed and generator, decoded from the run archive, or copied from the
gt1s2L rebench sidecars. [`manifest.json`](manifest.json) records per-file
provenance and verification.

Native formats only (no `.npy`): `.txt` = flow-shop processing-time matrix
(`n m` header then rows), `.cnf` = DIMACS, `.tsp`/`.hcp` = TSPLIB explicit /
edge-list. `champions/` (the 68 headline instances) is untouched.

## Verification

Every instance is re-solved (or, for the copied bundle, its source is recorded).
Whether the re-solve reproduces the recorded value depends on the solver:

- **Time-reproduced — SAT portfolio, CP-SAT/CP-Optimizer, and TSP/Concorde.**
  These re-solve back to the recorded hardness:
  - **6×4 CP-SAT champion** — **19.8 s vs 20.846 s (0.95×)**; the seeds-1..7
    signature `13.6 / 19.8 / 17.8 / 20.8` (min/median/geomean/max) matches the
    `agg_sensitivity_table` row `14.3 / 20.8 / 18.9 / 22.2`, confirming the exact
    instance.
  - **SAT phase-transition** — 1.02 s vs 1.011 s (**1.01×**).
  - **TSP controls** — matrix best-find **1.00×**, matrix best-held-out **1.01×**,
    euclid **0.99×**. The bred-family TSP matrices are genuinely structured
    (near-uniform degeneracy), so their Concorde times are stable.
  - Short uniform CP controls (6×4, 8×4) show CP-SAT's known short-solve timing
    variance (0.77–1.72×); correct by construction (deterministic seed / saved
    matrix).

- **Regeneration-verified — Ham HCP / Concorde only.** Ham HCP proof time near
  the feasibility boundary is noise-dominated and regresses to the mean (a
  central thesis finding: the hardest-of-100k value is a *selection-time peak*,
  not intrinsic difficulty — `HB.bench` itself now returns 0.19 s for the 0.456 s
  RS-triv peak). These instances are therefore guaranteed correct by
  **deterministic regeneration** (regenerating from the seed twice yields a
  byte-identical instance, asserted at build time). In `manifest.json`,
  `recorded_peak_s` is the selection-time value and `resolved_median_s` the
  current (lower) re-solve.

## Contents

### `jssp/` — non-permutation flow shop, F_m‖C_max
| file | todo | shape | provenance | check |
|---|---|---|---|---|
| `champ_MetaModelDiagonalCMA_6x4.txt` | P0.1 | 6×4 | `JSSP/logs_arch_gt1` `mat_neg_p` / MetaModelDiagonalCMA / it0 (values argmax) | 0.95× ✓ |
| `uniform_8x4_cpsat.txt` | P0.2 | 8×4 | hardest of 100k uniform (saved `uniform_hardest_8x4.npy`) | det. |
| `uniform_6x4_cpsat.txt` | ctrl.7 | 6×4 | `default_rng(1967).integers(1,101,(6,4))` | det. |
| `uniform_6x4_cpopt.txt` | ctrl.7 | 6×4 | `default_rng(44540).integers(1,101,(6,4))` | det. |
| `rs_uniform_10x5.txt` | ctrl.8 | 10×5 | `fssp_why_hard.rand_uniform(10,5,11097)` (hardest of 100k) | 0.85× |

### `sat/`
| file | todo | shape | provenance | check |
|---|---|---|---|---|
| `phase_transition.cnf` | ctrl.11 | 200v 854c | `random.Random(11687)` 3-CNF r=4.27 | 1.02× ✓ |
| `rs_mpfx.cnf` | ctrl.4b | 200v | `logs_arch_gt1` `mpfx_pow2` / RandomSearch / it1 (argmax) | control |
| `gt1s2L_source/` | P0.3 | — | config + evaluation IDs for the two headline CNFs (see below) | — |

`gt1s2L_source/` bundles `sweep_report.md`, `args.json` (rebench protocol,
k=10 reps=5), `inventory.json` (archive config), and `headlines.json` — which
ties each committed headline CNF to its source cell:
`champ_MultiScaleCMA_kcnf_gt1s2L.cnf` ← `kcnf_neg` / MultiScaleCMA / it1 / idx1;
`champ_TripleCMA_mpfx_gt1s2L.cnf` ← `mpfx_log` / TripleCMA / it2 / idx0.

### `ham/` — N=20, Concorde HCP reduction (concorde noise-dominated)
| file | todo | provenance |
|---|---|---|
| `rs_triv.hcp` | ctrl.6 | RandomSearch of the trivial encoding, seed 47239 |
| `rs_pint.hcp` | ctrl.6 | RandomSearch of the perm_int encoding, seed 14946 |
| `rs_pthr.hcp` | ctrl.6 | RandomSearch of the perm_thr encoding, seed 45540 |
| `gnp20_022.hcp` | ctrl.10 | `networkx.gnp_random_graph(20, 0.22, seed=93214)` |
| `cubic20.hcp` | ctrl.10 | `networkx.random_regular_graph(3, 20, seed=72859)` |

### `tsp/` — N=20, Concorde (re-solves reproduce the recorded value, ≈1.00×)
| file | todo | provenance | check |
|---|---|---|---|
| `rs_matrix_find.tsp` | ctrl.5 | `default_rng(56528)` integer matrix (best-find) | 1.00× ✓ |
| `rs_matrix_heldout.tsp` | ctrl.5 | `default_rng(77405)` integer matrix (best held-out 8..30) | 1.01× ✓ |
| `euclid.tsp` | ctrl.9 | `default_rng(47370)` 20 points in [0,500]², rounded Euclidean | 0.99× ✓ |

## Reproducing the random controls

Every random control is exactly the winner of the rf100k hardest-of-100k search,
regenerable standalone from its seed:

- **TSP matrix**: `D = np.random.default_rng(seed).integers(1, 1001, (20, 20))`, then `D = np.triu(D, 1); D = D + D.T`.
- **TSP euclid**: `pts = np.random.default_rng(seed).integers(0, 501, (20, 2))`; `D[i,j] = round(hypot(dx, dy))`.
- **NPFS uniform**: `np.random.default_rng(seed).integers(1, 101, (n, m))`.
- **Ham RS ⟨enc⟩**: build `My_Test(20, encoding=enc)`, `param = mt.encode()`, `param.random_state.seed(seed + 1)`, decode `param.sample().value`.
- **Ham gnp / cubic**: `nx.gnp_random_graph(20, 0.22, seed)` / `nx.random_regular_graph(3, 20, seed)`.
- **SAT phase-transition**: `random.Random(seed)`, 854 clauses of 3 distinct signed variables over 200 vars (r = 4.27).

## Not recoverable

- **`rs_kcnf`** (SAT k-CNF RandomSearch control): no `RandomSearch` cell was
  archived under any `log_gt1_sat_kcnf_*` config — only `mpfx_pow2` has one.
  Producing it requires a fresh RandomSearch run over the k-CNF encoding. It is
  recorded as `MISSING` in `manifest.json`.
