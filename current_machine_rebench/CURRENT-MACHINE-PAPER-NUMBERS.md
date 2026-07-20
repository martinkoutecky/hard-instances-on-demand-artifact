# Current-machine numbers for the ALENEX paper

Status: audited 2026-07-19 against paper commit `864940d` and the completed
campaigns on the AMD Ryzen 5 8600G.

This is the handoff file for refreshing the paper. It deliberately distinguishes
finished measurements from claims that should be removed, qualified, or run
again. Do not copy values from the old paper or from a superseded JSON summary
when this file names a later source.

## 1. Coverage verdict

The generated-instance headline rows are complete on the current machine:

- SAT champions, both fresh 100,000-draw RandomSearch controls, and the three
  hand-crafted controls;
- TSP champions, fresh RandomSearch, stored controls, and the fixed `gr229` and
  `20009_hard` comparators;
- HAM champions, nulls, and a fresh 100,000-draw RandomSearch campaign for each
  of the three encodings;
- NPFS generated champions and controls at 6x4, 8x4, and 10x5.

The full TSPLIB, Hard-TSPLIB, FHCP, and SAT Competition comparison sweeps also
exist. They have protocol qualifications recorded below.

All final headline/table measurements are therefore available on the new
baseline. The Stage-1 screening appendix and the 3.2 s endpoint in the
Stage-1-to-Stage-2 sentence are intentionally historical screening results;
they are not intended as measurements on the thesis reference machine and do
not need rerunning. The paper should identify that provenance rather than put
them under a blanket final-reference-machine claim.

The following two final-result prose claims still lack a current-machine
counterpart:

1. the SAT claim that a "typical" random ratio-5 formula is 600x faster;
2. the NPFS claim that a typical random 8x4 instance takes 0.025 s (and the
   derived 290x factor, if retained).

Remove those two undefined "typical random" claims or run explicitly defined
samples. Complete VRF and Demirkol timing rows also remain unavailable if the
paper is expanded to report them numerically; they are not in the current
paper.

## 2. Canonical source order

All paths are relative to the experimental repository root.

1. `current_machine_rebench/results/paper_instances.json`
   - canonical for SAT, external SAT, and NPFS;
   - exception: its 8x4 NPFS random control is the wrong recovered file and is
     superseded by item 2;
   - its TSP and HAM sections are superseded by items 2 and 3.
2. `current_machine_rebench/results/followup-four-core/`
   - `tsp-full-r3.json`: final generated TSP values, three repetitions per seed;
   - `ham-full-r3.json`: final generated HAM values, three repetitions per seed;
   - `tsp-gr229.json` and `tsp-20009.json`: final fixed external comparators,
     three repetitions per seed;
   - `tsp-random-final.json`: fresh 100,000-draw TSP RandomSearch plus clean
     top-20 remeasurement;
   - `npfs8-control.json`: fresh 100,000-draw 8x4 uniform control plus clean
     top-20 remeasurement on seeds 1--30.
3. `current_machine_rebench/results/ham-random-four-core/`
   - fresh 100,000-draw HAM RandomSearch for each encoding, with the top 20 from
     each screen remeasured three times on seeds 1--30.
4. `current_machine_rebench/results/tsp-suite.json`
   - canonical only for the broad 58-instance TSPLIB, 40-instance Hard-TSPLIB,
     and 12-instance generated clustered-Euclidean scans.
5. `current_machine_rebench/results/ham-suite.json`
   - canonical only for the broad 11-instance FHCP scan.
6. `comparisons/sat_comp/SAT-COMP-REPORT.md` and
   `comparisons/sat_comp/results/`
   - canonical for the 498-formula SAT Competition comparison.
7. `comparisons/npfs/taillard20x5-official-npfs.json`
   - canonical completed official-Taillard NPFS comparison.

Do not use smoke JSONs. Do not use the preliminary SAT champion file in
`current-machine-baseline`. Do not use
`paper_instances.summary.npfs.control_8x4_cpopt` (0.119 s). Do not use the TSP
or HAM headline summaries imported into `paper_instances.json`.

## 3. SAT replacement values

The paper objective is the virtual-best minimum over the first three columns.
Kissat and March are transfer/context columns, not members of that objective.
Each branch is the median of five sequential repetitions. `>60` means the
branch was censored at the 60 s cap.

| Instance | MiniSat | BreakID + CaDiCaL | CryptoMiniSat | Kissat | March | three-solver score |
|---|---:|---:|---:|---:|---:|---:|
| phase-transition random | 0.935 | 1.064 | 6.310 | 1.176 | 0.120 | 0.935 |
| PHP(12,11) | >60 | 0.00854 | >60 | 36.176 | 59.575 | 0.00854 |
| fresh GBD Tseitin, 150v/400c | >60 | 0.00803 | 0.801 | 10.414 | >60 | 0.00803 |
| van der Waerden W(2;3,13) | >60 | >60 | >60 | >60 | >60 | >60 |
| fresh RandomSearch, k-CNF | 0.0716 | 0.100 | 0.159 | 0.194 | 0.0203 | 0.0716 |
| fresh RandomSearch, mprefix | 0.468 | 0.622 | 2.449 | 0.587 | 0.0847 | 0.468 |
| k-CNF champion | 11.976 | 17.835 | >60 | 9.213 | 0.629 | 11.976 |
| mprefix champion | 11.091 | 13.606 | 53.381 | 10.175 | 0.419 | 11.091 |

Use 11.976 s as the headline SAT champion and 0.468 s as the strongest fresh
budget-matched RandomSearch control. The derived comparisons are 25.6x over
RandomSearch and 12.8x over the phase-transition random instance.

The historical Tseitin input was not archived. The measured row is a pinned,
fresh same-size GBD Tseitin replacement and must be described that way.

### SAT Competition

There are 498 unique formulas. Relative to the weaker current champion
(11.091 s), 387 are definitely strictly faster, or 77.7% (78% rounded). The
old 388 count used the former 11.6 s threshold; no new solve is needed to
change it because the existing corpus files contain the per-formula values.
The broad corpus was screened once with a 12 s cap; selected representatives
were remeasured at longer caps. Do not imply that all 110 screen-censored
formulas were exactly timed.

## 4. TSP replacement values

Final generated and fixed-comparator values use three repetitions per seed,
the geometric mean within each seed, and the median over seeds 1--7 (train) or
8--30 (held-out).

| Instance | train | held-out |
|---|---:|---:|
| random Euclidean | 0.0777 | 0.0728 |
| fresh RandomSearch screen winner | 0.845 | 0.751 |
| fresh RandomSearch conservative best-held-out candidate | 0.696 | 0.786 |
| CMA champion | 9.966 | 1.311 |
| Shiwa champion, U=1000 | 13.516 | 7.992 |
| DiagonalCMA champion, U=10000 | 17.307 | 12.863 |
| TSPLIB `gr229` | 2.338 | 2.241 |
| Hard-TSPLIB `20009_hard` | 33.751 | 28.701 |

The two RandomSearch rows are two actual instances. For a table row explicitly
called "best-held-out RandomSearch", use 0.696/0.786. Do not construct the
coordinate-wise hybrid 0.845/0.786: no single instance has that pair.

The old 4.94/0.10 RandomSearch collapse did not reproduce in the fresh screen
and should be removed. The CMA champion still supplies a clean seed-overfitting
example: 9.966 -> 1.311, a 7.60x decrease.

Derived held-out comparisons are 3.57x for Shiwa versus `gr229` and 5.74x for
DiagonalCMA versus `gr229`.

### Broad external TSP scan

These are one solve per seed, not three; say so in Method or the table caption.

- TSPLIB: 58 cases, median of train medians 0.0967 s.
- Locally generated clustered-Euclidean: 12 cases, median 0.1697 s.
  No van Hemert corpus was recovered, so the current label "van Hemert
  clustered" is unsupported and must be renamed.
- Hard-TSPLIB: 23/40 cases have a seven-seed median censored at 60 s, not 24/40.
- `dantzig42_hard` has the slowest finite train median, 43.045 s, but two of
  seven seeds time out.
- `20009_hard` is the hardest broad-scan case for which all seven train seeds
  solved; use the three-repeat fixed-comparator row above in the paper.

## 5. HAM replacement values

Final generated values use three repetitions per seed and the same
geometric-mean/median aggregation as TSP.

| Instance | train | held-out |
|---|---:|---:|
| random cubic | 0.0405 | 0.00894 |
| G(20,0.22) null | 0.255 | 0.169 |
| fresh RandomSearch, conservative best of three encodings | 0.351 | 0.275 |
| TwoPointsDE champion | 0.613 | 0.272 |
| NGOptRW champion | 0.861 | 0.319 |
| DiscreteBSO champion | 1.119 | 0.484 |

The fresh RandomSearch row is one permutation-plus-edge-count candidate and is
the conservative maximum under both clean train and held-out comparisons. The
champion/random ratios are 3.19x train and 1.76x held-out. Thus the relative
result reproduces even though the absolute champion time is lower than on the
old machine.

### FHCP

The broad scan uses one solve per seed. Six of eleven cases have a seven-seed
median censored at 60 s.

- `graph8` is the hardest member solved on all seven measured seeds: 7.875 s.
- `graph5` has a finite median of 43.234 s but three of seven seeds time out.

If the paper keeps "hardest solved", define it as "hardest solved on all seven
seeds" and use `graph8`; otherwise report `graph5` with its timeout count.

## 6. NPFS replacement values

| Row | CP-SAT train | CP-Optimizer train | own-engine held-out |
|---|---:|---:|---:|
| 6x4 CP-SAT champion | 18.169 | 0.334 | 16.260 |
| 6x4 CP-SAT-arm RandomSearch | 0.213 | 0.0215 | 0.247 |
| 6x4 CP-Optimizer champion | 0.781 | 0.543 | 0.522 |
| 6x4 CP-Optimizer-arm RandomSearch | 0.140 | 0.180 | 0.179 |
| 8x4 CP-Optimizer champion | >60, feasible only | 7.235 | 7.034 |
| 8x4 fresh uniform RandomSearch | -- | 0.668 | 0.649 |
| 10x5 CP-Optimizer champion | >600, feasible only | 238.637 | 235.306 |
| 10x5 uniform RandomSearch | -- | 4.495 | -- |

The generic 6x4 "random uniform" row in the current table is redundant and
has ambiguous provenance. Prefer the two explicit same-arm controls above.

Derived train/held-out ratios are:

- 8x4 champion versus fresh control: 10.83x / 10.84x;
- 10x5 champion versus control: 53.1x train;
- 6x4 CP-SAT arm versus its control: 85.3x / 65.8x;
- 6x4 CP-Optimizer arm versus its control: 3.02x / 2.91x.

### External NPFS state

The current paper mentions only external-suite sizes, so incomplete VRF and
Demirkol timings do not block refreshing its existing numbers. They do block
adding a complete new external-comparison timing table.

- Official Taillard 20x5 is complete: 100/100 solves are optimal; `ta005` is
  hardest with a per-instance median of 3.397 s.
- The correctly generated Taillard-style 10x5 diagnostic is complete; its
  hardest median is 0.679 s. Label it generated, not an official Taillard
  benchmark.
- VRF 10x5 is incomplete: 21 planned solves exist, with no instance complete
  across all ten seeds.
- The requested unrestricted CP-Optimizer Demirkol seeds-1--10 run produced no
  result; its log is empty and its process is dead.

To add the desired external NPFS timing paragraph, resume/restart VRF and run
Demirkol under a declared cap or unrestricted protocol. Taillard can be
reported now.

## 7. Claims that need removal, qualification, or a small new run

### Remove or make qualitative now

- SAT typical-random 600x claim: the fresh control campaign retained the top
  candidates, not a defined typical distribution statistic.
- NPFS typical-random 8x4 0.025 s and 290x: the fresh campaign likewise retained
  the top 20 rather than a typical-sample distribution.
- TSP RandomSearch 4.94/0.10 and its 49x collapse: not reproduced by the fresh
  100,000-draw control.

### Historical screening numbers

The current campaign intentionally did not remeasure the Stage-1 appendix or
the 3.2 s Stage-1 SAT endpoint. Keep them as results of the original screening
campaign. The saved cell winners and old verification manifest remain under
`champions/`.

The writing change required here is provenance, not new computation. In
particular, the current Method says that "every number reported anywhere in
this paper" comes from the final reference machine, and the Hardware appendix
says the reference machine supplies "every reported number." Narrow both
statements to final/headline remeasurements and explicitly exclude the
historical screening table. The screening caption can say that its seconds are
the original screening campaign's clean-rebench values.

### Structural observations

Most structural numbers are machine-independent instance properties and do not
need timing migration. The saved instances permit the SAT, TSP, HAM, and NPFS
statistics to be recomputed. Two receipts are weak: the paper has no committed
machine-readable record for the TSP 271/300 two-opt claim, and the NPFS
row/column ratios are documented only in LaTeX comments. Reproduce or soften
those claims independently of the timing refresh.

## 8. Hardware and protocol text

Replace the old Ryzen 7 7840HS statement. The current machine is an AMD Ryzen 5
8600G (6 physical cores/12 threads). Each individual solver was pinned to one
logical CPU and configured single-threaded. Multiple independent experiments
ran on distinct physical cores; the final follow-up and HAM RandomSearch runs
maintained approximately four loaded physical cores.

Boost could not be disabled and was enabled throughout. Frequency and
temperature samples are in:

- `current_machine_rebench/results/cpu-frequency.csv`;
- `current_machine_rebench/results/followup-four-core/cpu-frequency.csv`;
- `current_machine_rebench/results/ham-random-four-core/cpu-frequency.csv`.

Do not describe this machine as dedicated and otherwise idle. Do not claim that
only one experiment existed machine-wide; the defensible statement is that
each final-reference solve was sequential, single-core, and compared under the
same local campaign conditions. Historical screening measurements are outside
this hardware statement.

The broad TSPLIB/Hard-TSPLIB/FHCP sweeps used one solve per seed. The final
generated TSP/HAM values and fixed TSP comparators used three repetitions per
seed. State this deviation explicitly instead of applying one blanket
aggregation sentence to every row.

## 9. Paper-file checklist

At paper commit `864940d`, a refresh must inspect at least:

- `numbers.tex`: volatile headline macros and derived ratios;
- `results.tex`: all four literal-valued tables and surrounding comparisons;
- `summary-table.tex`: duplicated headline/external values;
- `main.tex` and `intro.tex`: rounded headline values and SAT Competition count;
- `protocol.tex`: preserve the Stage-1 3.2 s value but distinguish historical
  screening measurements from final reference-machine remeasurement;
- `setup.tex` and `appendix.tex`: machine and aggregation descriptions;
- `discussion.tex`: old TSP seed-overfitting numbers;
- `appendix.tex`: retain the screening table while identifying its original
  measurement provenance.

After updating, search all `\renum`, rebuild with the repository's full LaTeX
sequence, check citations/references/overfull boxes, and inspect the rendered
pages. Keep the historical screening seconds and the new final-table baseline
as explicitly different measurement strata.
