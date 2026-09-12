# Hard Instances on Demand -- ALENEX 2027 artifact

**Paper:** *Hard Instances on Demand*
**Authors:** Pasha TODO-SURNAME, Martin Koutecký, Jamie TODO-SURNAME
Accepted at the 2027 SIAM Symposium on Algorithm Engineering and Experiments
(ALENEX 2027).

Code and data for a problem-agnostic protocol that evolves hard instances for a
given solver by black-box optimization (Nevergrad), validated on SAT
(three-solver portfolio), TSP (Concorde), Hamiltonian cycle (Concorde
reduction), and non-permutation flow shop / F_m||C_max (CP-SAT and CP
Optimizer).

Licensed under the Apache License 2.0 (`LICENSE`). Third-party solver binaries
redistributed under `dpll4_portfolio/bin/` and `SAT/` keep their own licenses.

## Quick start

```sh
./runme.sh          # ~1 minute, runs no solver, needs no dependencies
```

That pass (1) reports which optional dependencies are present, (2) validates
the shipped inventory, (3) re-verifies all 194 referenced instance files
against the sha256 recorded when they were measured, and (4) **recomputes the
paper's aggregate tables from the committed measurement files**, using the same
aggregation code that produced the published numbers
(`current_machine_rebench.run_rebench.summarize`). Output lands in
`runme_out/`.

```sh
pip install -r requirements.txt
./runme.sh --smoke  # + one small solve per suite: validates the toolchain
./runme.sh --full   # + the complete remeasurement campaign (many hours)
```

Re-running the searches themselves is *not* required to check the paper's
tables; see "Re-running the remeasurement" below for what each tier costs.
`current_machine_rebench/CURRENT-MACHINE-PAPER-NUMBERS.md` maps every result
file to every number in the paper -- read it first.

## Layout

The directory tree mirrors the experimental repository, so all committed
configurations and scripts run unmodified from the packet root.

| Purpose | Location |
|---|---|
| Search + solution drivers | `SAT/`, `TSP/`, `Ham/`, `JSSP/` (`exp.py`, `ng_class.py`, `solution*.py`, all `config_gt1*`/Stage-2 configs), shared harness in `template/`, four-solver SAT transfer portfolio in `dpll4_portfolio/` |
| Clean remeasurement (reference machine) | `current_machine_rebench/` (scripts + `results/`) |
| Exported champion instances | `champions/{sat,tsp,ham,jssp}/` |
| Reconstructed control instances | `todo_instances/` (see its `README.md` + `manifest.json`) |
| External benchmark instances | `current_machine_rebench/results/external/instances/` + `prepared_manifest.json` (sha256 per instance); regeneration scripts in `comparisons/external_benchmarks/` |
| SAT Competition comparison | `comparisons/sat_comp/` (scripts, `manifest.csv` of GBD hashes, `results/`, `SAT-COMP-REPORT.md`) |
| NPFS external comparisons | `comparisons/npfs/` |
| Headline-file record | `ALENEX_MANIFEST.md`, `alenex/manifest.json` |

`current_machine_rebench/CURRENT-MACHINE-PAPER-NUMBERS.md` is the canonical
map from result files to every number in the paper; read it first. Its "Do not
use" list explains files intentionally absent here (smoke results, superseded
summaries).

## Paper table -> results file map

All measurements below were taken on one machine: AMD Ryzen 5 8600G
(6 cores/12 threads), each solve pinned to one logical CPU, single-threaded.

| Paper numbers | File(s) in this packet |
|---|---|
| SAT champion/control table (per-branch medians, virtual-best score) | `current_machine_rebench/results/paper_instances.json` (fresh 100,000-draw RandomSearch controls also in `current_machine_rebench/results/sat_randomsearch/`) |
| SAT Competition comparison (498 formulas, 78% faster share) | `comparisons/sat_comp/results/` (esp. `aggregate.json`, `full_cap12_shard*.json`), narrative in `comparisons/sat_comp/SAT-COMP-REPORT.md` |
| TSP generated champions, train/held-out | `current_machine_rebench/results/followup-four-core/tsp-full-r3.json` |
| TSP fixed external comparators `gr229`, `20009_hard` | `current_machine_rebench/results/followup-four-core/tsp-gr229.json`, `tsp-20009.json` |
| TSP fresh 100,000-draw RandomSearch control | `current_machine_rebench/results/followup-four-core/tsp-random-final.json` (+ `tsp_random_candidates/`) |
| Broad TSPLIB / Hard-TSPLIB / clustered-Euclidean scan | `current_machine_rebench/results/tsp-suite.json` |
| HAM generated champions and nulls | `current_machine_rebench/results/followup-four-core/ham-full-r3.json` |
| HAM fresh RandomSearch (three encodings) | `current_machine_rebench/results/ham-random-four-core/` |
| Broad FHCP scan | `current_machine_rebench/results/ham-suite.json` |
| NPFS 6x4/8x4/10x5 champions and controls | `current_machine_rebench/results/paper_instances.json`; fresh 8x4 uniform control in `current_machine_rebench/results/followup-four-core/npfs8-control.json` |
| Official Taillard 20x5 NPFS comparison | `comparisons/npfs/taillard20x5-official-npfs.json` |
| Official VRF 10x5 NPFS comparison | `measurements/vrf-npfs/vrf10x5-official-npfs.json` |

| CPU frequency/temperature conditions | `current_machine_rebench/results/cpu-frequency.csv` and the per-campaign `cpu-frequency.csv` under `followup-four-core/` and `ham-random-four-core/` |
| "Typical random" medians (SAT kcnf, NPFS 8x4 and 10x5) | `measurements/typical-random/` (receipts, script, frequency log) |
| Four-solver paradigm-diverse SAT champions (1.36 s portfolio min, 130x typical) | instances/configs/objective in `dpll4_portfolio/`; reference-machine per-branch remeasurement and typical control in `measurements/dpll4-remeasure/` |
| Official VRF 10x5 under NPFS (hardest median 3.8 s, champion 62x) | `measurements/vrf-npfs/` (instances + model in `comparisons/vrf_cpopt_10x5/`) |

Note on the external NPFS medians: the paper quotes Taillard/VRF medians
over solver seeds 1-7 (ta005 4.512 s, VFR10_5_2 3.808 s) to match the
champion's evaluation-seed protocol. The JSONs contain all ten per-seed
values; the 10-seed medians (3.397 s / 3.813 s) differ for ta005 because
its per-seed times vary.

Historical Stage-1 screening numbers in the appendix are results of the
original screening campaign (see `ALENEX_MANIFEST.md`), not of this
remeasurement; the saved cell winners are under `champions/`.

## Re-running the remeasurement

1. Environment: Python 3.12 with `nevergrad`, `python-sat` (1.9.dev2, provides
   `minisat22` and `cadical195`), `pycryptosat` (5.14.4), `ortools` (CP-SAT),
   `numpy`. External binaries: Concorde (TSP/HAM), IBM CP Optimizer (point
   `CPOPT_EXECFILE` at your `cpoptimizer` binary; NPFS rows need it).
   Linux x86-64 binaries for the SAT transfer portfolio are included under
   `dpll4_portfolio/bin/` (`breakid`, `kissat`, `march_cu`) and `SAT/`
   (`breakid`, `libbreakid.so`).
2. Serial campaign (SAT/TSP/HAM/NPFS + external families):
   `current_machine_rebench/run_all.sh` (checkpointed; see
   `current_machine_rebench/README.md` for the protocol, solver pinning, and
   virtual-best scoring). Follow-up four-core campaigns:
   `run_followup_four_core.sh`, `run_ham_random_four_core.sh`.
3. External TSP/HAM corpora: the third-party archives (TSPLIB `ALL_tsp.tar.gz`,
   FHCP `FHCPCS.7z`, Hard-TSPLIB at commit `74b142a`) are NOT redistributed
   here. `comparisons/external_benchmarks/prepare_instances.py` re-downloads
   and verifies them; the prepared per-instance files and their sha256s are
   already included under `current_machine_rebench/results/external/`.
4. SAT Competition corpus: not redistributed. `comparisons/sat_comp/
   fetch_instances.py` reconstructs all 498 formulas from the Global Benchmark
   Database using `manifest.csv`; `benchmark_portfolio.py` reruns the
   comparison.
5. Re-running the original searches: each domain directory contains the
   committed Stage-1/Stage-2 configs (`config_gt1*`), e.g.
   `python3 SAT/exp.py --file SAT/config_gt1s2_sat_kcnf_log.json` from the
   packet root. Budgets are large; searching is not required to verify the
   paper's tables.

## Anonymization notes (retained from the double-blind review packet)

These transformations were applied for double-blind submission and are
left in place so that the published artifact stays byte-comparable with
the reviewed one. They affect provenance records only; no script depends
on them.

- Path placeholders. Historical absolute paths in result JSONs, logs, and
  scripts were rewritten: paths inside the experiment repository are now
  packet-relative; machine-specific prefixes appear as `<software>` (CPLEX
  install), `<conda-env>` (Python env), `<legacy-repo>` (pre-consolidation
  experiment archive), `<home>` (original search logs), `<workdir>`. These
  fields are provenance records only; no script depends on them.
- One TSP champion originally carried a contributor's first name as a
  filename suffix and in its TSPLIB `NAME:` header. The file is included as
  `champions/tsp/champ_DiagonalCMA_U10000.tsp` (suffix dropped) and the
  header line was anonymized to match. The distance matrix
  is byte-identical. Consequence: sha256 values recorded for this one instance
  in older result JSONs refer to the pre-anonymization content
  (`aa0a7b837408b58a88b3670cd88094c521e085d1b6a010eed59b9ebde213ac44`); the
  packet file hashes to
  (`2ee333c985c78f0b5ebb2f94e7bf160c35f9ab59b76917d4a6115f4592d24495`).
  Only the `NAME:` header line differs. All other instance hashes are
  untouched and verify as recorded.
- `dpll4_portfolio/bin/kissat`: a 5-byte build-host name inside the compiled
  build-info string was replaced by `anon-` (same length; code unmodified).
  Its recorded sha256 in `solver_inventory` therefore refers to the unpatched
  binary.
- `machine.hostname` fields contain `8f9fd2be337b`, the ephemeral ID of the
  measurement container, not a personal or institutional hostname.
- A git branch name and a JSON key equal to a contributor's name were replaced
  by neutral labels (`origin/<experiments-branch>`, `"experiments"`).

## Omissions (relative to the full experimental repository)

- `current_machine_rebench/results/external/cache/` (~17 MB): unmodified
  third-party archives (TSPLIB, FHCP, Hard-TSPLIB); re-downloadable and
  checksum-verified by `comparisons/external_benchmarks/prepare_instances.py`.
- SAT Competition CNFs: never stored here; reconstructed via
  `comparisons/sat_comp/fetch_instances.py` + `manifest.csv` (GBD hashes).
- `smoke-results/` and `smoke-*.json`: explicitly non-canonical shakedown
  runs ("Do not use smoke JSONs" in the numbers document).
- Incomplete VRF 10x5 comparison runs: not reported in the paper (the paper
  cites external-suite sizes only); omitted as unfinished.
- Internal coordination notes (status/worklist files), `.git` metadata,
  `__pycache__`, checkpoint pickles (`*.state.pkl`), lock and pid files.
- The March look-ahead solver's original build tree; the pinned `march_cu`
  binary itself is included under `dpll4_portfolio/bin/`.

## Known reproducibility boundary

The committed configurations and exported champions are authoritative, and
every paper table can be recomputed from the included result files. However,
the ignored Stage-1 remeasurement checkpoints that guided the Stage-2
optimizer-subset selection were not recovered; the final searches can be rerun
from the committed configs, but the complete screening-to-selection derivation
cannot be reconstructed independently (see `ALENEX_MANIFEST.md`, section 5).
