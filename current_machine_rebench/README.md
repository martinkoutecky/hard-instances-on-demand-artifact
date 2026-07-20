# Current-machine paper rebenchmark

For the audited source hierarchy, paper-ready replacement values, superseded
artifacts, and remaining exclusions, see
[`CURRENT-MACHINE-PAPER-NUMBERS.md`](CURRENT-MACHINE-PAPER-NUMBERS.md).

This directory prepares one serial, single-logical-CPU campaign for the ALENEX
paper tables. It covers the instances in `todo_instances/`, selected existing
champions, the four new SAT portfolio champions, and the external SAT, TSP,
and HAM comparison families. Every solve is checkpointed in JSON; the SAT
RandomSearch state is checkpointed separately and resumes automatically.

## Why a new runner is necessary

Two details in the archived code would otherwise invalidate the comparison.

1. Both SAT portfolio modules auto-select the first available strong CDCL
   backend. On this machine that is `kissat404`, although the paper and
   manifests say BreakID followed by CaDiCaL 1.9.5. This runner pins that
   branch to `cadical195` and records solver versions and binary hashes.
2. Both archived portfolio evaluators launch their branches concurrently.
   Here the branches are timed sequentially and their virtual-best CPU-time
   minimum is computed afterward, so there is never more than one active
   solver branch. TSP, HAM, CP-SAT, and CP Optimizer are likewise run one solve
   at a time; CP-SAT and CP Optimizer are configured with one worker.

The BreakID branch preserves the experiment's scoring convention: a fixed
8 ms charge is added to CaDiCaL time instead of measuring BreakID preprocessing
end to end. The report calls the result a virtual-best score rather than a
literal wall-clock portfolio runtime.

## SAT controls

Run fresh 100,000-draw RandomSearch controls for **both** paper encodings. The
newly recovered `todo_instances/sat/rs_mpfx.cnf` is from a 15,000-evaluation
Stage-1 run and therefore cannot support the paper's 100k claim. Sampling uses
the exact Nevergrad `RandomSearch` distribution (`parameter.sample()`), master
seed `20260601`, and the median of three portfolio evaluations. The top 20
candidates are retained, then `run_rebench.py` measures each candidate five
times per solver. This lets the final paper control be chosen and reported from
clean branch-level data without losing the selection record.

The four-solver experiment should be treated as an auxiliary portfolio
escalation, not a replacement for the original SAT headline. It changes two
factors at once (adds March and replaces MiniSat with Kissat), and currently
lacks a matched random control. Set `RUN_DPLL4_RANDOMSEARCH=1` to add a matched
100k mprefix control before using it as evidence that guided search beats
random guessing under the new objective.

## Full command

Choose an otherwise idle logical CPU. The default is CPU 1:

```bash
./current_machine_rebench/run_supervised.sh 1
```

The supervisor holds an exclusive campaign lock and relaunches `run_all.sh`
after a nonzero exit. Every phase is checkpointed, so a restart resumes rather
than repeating completed work. For an interactive diagnostic run without
automatic restart, invoke `run_all.sh` directly.

To include the additional four-solver RandomSearch:

```bash
RUN_DPLL4_RANDOMSEARCH=1 ./current_machine_rebench/run_supervised.sh 1
```

The scripts refuse to run unless their affinity contains exactly one logical
CPU. Threaded numerical libraries are fixed to one thread. Results go under
`current_machine_rebench/results/` and are intentionally ignored until the
campaign is complete and reviewed.

Allow roughly 13--26 hours for the default campaign on the Ryzen 5 8600G. The
two 100k SAT screens and the 30-seed 10x5 CP-Optimizer remeasurement dominate.
External-family instances use one solve per seed and stop only after enough
timeouts to determine the seeded median, which avoids spending repeated capped
runs on a median already known to be right-censored. The scripts are resumable,
so an interruption does not discard completed evaluations. The optional
four-solver RandomSearch adds several more hours.

The two independent RandomSearch screens may be launched concurrently on
different physical cores. Per-screen file locks ensure that a later invocation
of `run_all.sh` waits for an already-active screen instead of duplicating it:

```bash
./current_machine_rebench/run_sat_screen_supervised.sh 2 original3 mprefix
```

The TSP and HAM domains can likewise run concurrently on two further physical
cores. Each domain checkpoint contains both the generated and external cases,
so within-domain comparisons stay on one core. `run_all.sh` waits for their
locks and imports the rows into the final report without duplicate solves:

```bash
./current_machine_rebench/run_domain_suite_supervised.sh 3 tsp
./current_machine_rebench/run_domain_suite_supervised.sh 4 ham
```

CPU boost cannot be disabled without system-administrator access on this
machine. Record the frequency conditions continuously instead; pinning the
low-overhead logger to an otherwise unused sibling keeps it away from the
benchmark cores:

```bash
taskset -c 11 python3 current_machine_rebench/monitor_cpu_frequency.py \
  --output current_machine_rebench/results/cpu-frequency.csv
```

The CSV records every logical CPU once per second, load averages, the AMD Tctl
temperature when available, and whether sampled frequencies exceed each CPU's
configured `scaling_max_freq`. This is sufficient to detect boost, gross
frequency drift, and a temperature-correlated frequency collapse. With
`acpi-cpufreq` it is not a cycle-accurate APERF/MPERF measurement, which would
require privileged performance-counter or MSR access.

## Protocol covered

- SAT: five sequential repetitions of each named branch, plus fresh 100k
  RandomSearch controls. The original three-solver score is
  `min(MiniSat22, 0.008 + BreakID->CaDiCaL195, CryptoMiniSat)`. The auxiliary
  score is `min(Kissat, 0.008 + BreakID->CaDiCaL195, CryptoMiniSat, March)`.
- TSP and HAM: training seeds 1--7, three repetitions per seed and a geometric
  mean within each seed; held-out seeds 8--30, one solve per seed.
- NPFS: both engines for every cross-engine row shown in the paper, seeds 1--7;
  the instance's own engine on held-out seeds 8--30. Caps are 60 s, or 600 s
  for 10x5. Status, objective, and bound are retained where the solver exposes
  them.
- External SAT: canonical PHP(12,11), W(2;3,13), and a pinned
  150-variable/400-clause GBD Tseitin representative, measured branch by branch
  under the same portfolio. The Tseitin input is explicitly marked as a fresh
  replacement because the original graph was not archived.
- External TSP: all 58 official TSPLIB `TYPE:TSP` instances of dimension at
  most 300, all 40 files released in Hard-TSPLIB, and twelve deterministic
  clustered-Euclidean instances. Train uses one solve for each of seeds 1--7;
  the two fixed paper comparators, `gr229` and `20009_hard`, additionally use
  one solve for each held-out seed 8--30. A split stops early only after a
  strict majority of its planned seeds time out (four of seven train seeds or
  twelve of 23 held-out seeds), which proves that its median is right-censored
  at 60 s. These are predeclared historical comparators, not instances selected
  after inspecting this campaign's train sweep. Native TSPLIB files go directly
  through Concorde's parser.
- External HAM: FHCP `graph5` through `graph15` (90--150 vertices), seeds 1--7
  with one solve per seed, through the same 0/1 TSP reduction as the generated
  graphs. Four timeout seeds are required before classifying the seven-seed
  median as right-censored. Every Concorde solver call runs in a disposable
  subprocess with a 60 s process-CPU timer; a much larger wall guard detects
  worker failures but is never classified as a solver timeout.

`comparisons/external_benchmarks/prepare_instances.py` downloads and verifies
the official TSPLIB and FHCP archives, pins the Hard-TSPLIB release commit,
generates the deterministic families, and emits per-instance hashes. The
clustered row is named for what it actually is; no external van Hemert instance
corpus was recovered. Checkpoint metadata hashes all prepared instance bytes and
the working-tree state, so changed code or inputs cannot silently mix old and
new rows on resume.
