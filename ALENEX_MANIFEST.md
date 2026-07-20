# ALENEX experiment manifest

## 1. Scope

This is the authoritative map through the experiment repository. Files named
below are canonical for the thesis or current paper. Other remote branches
remain useful provenance, but are not implicitly part of this artifact.

The common workflow was instantiated differently in the four domains; the
configurations below, rather than one reconstructed universal recipe, are the
source of truth.

## 2. Canonical experiments

| Domain | Runner and objective | Canonical configurations | Exported instances |
|---|---|---|---|
| SAT | SAT/exp.py; minimum time of the required three-branch portfolio in SAT/solution_portfolio.py | six config_gt1_sat_* Stage-1 files and six config_gt1s2_sat_* Stage-2 files | 18 CNFs in champions/sat/, including the MultiScaleCMA k-CNF and TripleCMA mprefix headlines |
| TSP | TSP/exp.py; Concorde on 20-city symmetric integer distance matrices | six Stage-1 config_gt1_tsp_*, three Stage-2 config_gt1s2_tsp_*, and one config_gt1s2rs_* random-control search | 12 matrices in champions/tsp/; Shiwa at U=1000 is primary |
| HAM | Ham/exp.py; Concorde reduction on 20-vertex graphs | 18 Stage-1 config_gt1_ham_* and nine Stage-2 config_gt1s2_ham_* files | 26 graphs in champions/ham/ |
| NPFS | JSSP/exp.py; CP-SAT or CP Optimizer on F_m || C_max | 12 Stage-1 files (six per engine), three CP-Optimizer Stage-2 files, plus the 8x4 and 10x5 auxiliary configs | 12 matrices in champions/jssp/ (legacy path) |

The headline files are recorded explicitly in alenex/manifest.json.
champions/verification_thesis.json preserves the attachment's verification
output, but its timings have no machine metadata and must not be used as the
paper's reference-machine baseline.

### 2.1 SAT

Stage 2 uses 200 variables, 1,000 clauses, a budget of 100,000 evaluations,
five optimizer runs, and the median of three repeated portfolio measurements
per candidate. All twelve committed configs set require_full_portfolio=true;
a missing BreakID, strong-CDCL, or XOR branch is therefore an error rather
than a silent objective change.

The two headline filenames contain gt1s2L. Their final Chimera configs and
source mini-archives were not committed and are requested below. The ordinary
Stage-2 configs are present and remain the closest committed protocol record.

### 2.2 TSP

The primary paper result is
champions/tsp/champ_Shiwa_dm_log_p_it2.tsp, generated with U=1000 by the
Stage-2 log/parallel configuration.

The stronger auxiliary U=10000 DiagonalCMA experiment has its separate
50,000-evaluation, two-run configuration in TSP/exp_optimizer_compare.json;
its exported matrix is
champions/tsp/champ_DiagonalCMA_U10000.tsp.

### 2.3 HAM

The canonical search uses the triv, pint, and pthr graph encodings, three
transforms, and their serial/parallel Stage-1 screens. Stage 2 contains nine
parallel configs. The gt1s2r files on exploratory branches were
reproducibility replicas, not additional headline experiments.

### 2.4 NPFS

JSSP/solution.py and JSSP/solution_cpopt.py impose job precedence and an
independent no-overlap constraint on each machine. No constraint forces a
common job order across machines. The problem is therefore NPFS
F_m || C_max, not JSSP and not permutation flow shop.

- The 6x4 CP-SAT arm is a 15,000-evaluation Stage-1 solver-specificity
  experiment. It is retained because it illustrates severe solver
  specificity, not because CP-SAT is the paper's strongest scheduling result.
- The 6x4 CP-Optimizer arm uses the 100,000-evaluation Stage-2 configs.
- JSSP/exp_8x4_dia2pde.json records the 8x4, 100,000-evaluation auxiliary run.
- JSSP/exp_bench_10x5.json records the 10x5, 50,000-evaluation, two-run
  experiment whose exported champion is champ_DE_10x5.txt.

Do not restore the old JSSP/taillard.py: it used a modulo mapping that does
not reproduce Taillard's instances. Correct benchmark generation and
remeasurements are under comparisons/npfs/.

## 3. Paper comparison packages

- comparisons/vrf_cpopt_10x5/ re-solves the ten VRF 10x5 processing-time
  matrices and the generated 10x5 champion under the same NPFS CP-Optimizer
  model.
- comparisons/npfs/run_external_npfs.py handles the exported 8x4/10x5
  champions, the Demirkol suite, and exact Taillard generation.
- comparisons/npfs/taillard20x5-official-npfs.json is the corrected
  current-machine run of the published 20x5 Taillard group.
- comparisons/npfs/taillard-generator-10x5-cpopt.json is a same-size
  diagnostic generated with Taillard's exact RNG and the ten published 20x5
  seeds. It is not a member of the official 120-instance Taillard suite.

External benchmark collections should be represented by a fetch/checksum
manifest unless redistribution is appropriate. The consolidated package under
`comparisons/external_benchmarks/` downloads and verifies the official TSPLIB
and FHCP archives, pins Hard-TSPLIB at commit `74b142a`, regenerates the
clustered-Euclidean baseline and canonical SAT constructions, and writes a
per-instance checksum manifest. The former “van Hemert clustered” row has no
recovered external corpus; the artifact calls the actual local generator
`clustered_euclidean`. The historical 150-variable/400-clause Tseitin graph is
also missing, so the package pins a same-size GBD representative as a fresh
replacement rather than claiming byte identity.

The SAT Competition comparison is already packaged under
comparisons/sat_comp/. Its manifest identifies the 498 formulas, and
fetch_instances.py reconstructs the local corpus from the Global Benchmark
Database without committing duplicate compressed formulas.

## 4. Recovered selected instances and remaining controls

The instances formerly listed in this section were reconstructed under
`todo_instances/`; its README and manifest give the native file, source
run/seed, and verification for each item. This includes the 6x4 CP-SAT
champion, 8x4 and 10x5 scheduling controls, TSP and HAM controls, SAT
phase-transition formula, and final gt1s2L source sidecars.

One exact historical input remains unavailable: no archived RandomSearch cell
contains the k-CNF control. The recovered mprefix control is a 15,000-evaluation
Stage-1 candidate rather than the 100,000-draw control described in the paper.
The current-machine campaign therefore regenerates **both** 100,000-draw SAT
controls using seed 20260601 and preserves the top candidates and clean
branch-level remeasurements.

The serial runner is `current_machine_rebench/run_all.sh`. It remeasures all
reconstructed inputs, selected paper champions, and external SAT/TSP/HAM rows.
SAT portfolio branches are executed sequentially and their virtual-best CPU
minimum is computed afterward; the BreakID branch is explicitly pinned to
CaDiCaL 1.9.5 instead of relying on backend auto-detection. External Concorde
calls run in fresh capped subprocesses and native TSPLIB files are passed
unmodified to Concorde's reader. External TSP and FHCP families use one solve
per seed; early stopping requires a strict majority of timeout seeds, which is
enough to prove that the reported seeded median is right-censored at the cap.
`current_machine_rebench/monitor_cpu_frequency.py` records the per-core
frequency conditions when boost cannot be disabled by an unprivileged user.

External Taillard, VRF, Demirkol, SAT Competition, TSPLIB, Hard-TSPLIB, and
FHCP instances do not need to come from the thesis repository.

## 5. Reproducibility boundary

The committed configurations and exported champions are authoritative.
However, the ignored Stage-1 remeasurement checkpoints used to choose the
Stage-2 optimizer subsets were not recovered. Consequently, the final search
can be rerun from the committed configs, but the complete
screening-to-selection derivation cannot yet be reconstructed independently.
