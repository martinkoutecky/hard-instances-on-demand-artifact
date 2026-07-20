# SAT Competition comparison: small instances versus the Nevergrad champions

Date: 2026-07-17

## Bottom line

The defensible conclusion is neither "our instances beat SAT Competition" nor
"our instances are uninteresting by SAT Competition standards."

The two Nevergrad champions take 11.63 s and 12.47 s on this machine and are
in the competitive band for formulas with at most 200 variables and 1,000
clauses. Most competition formulas in this size range are much easier for the
paper's three-solver objective. A concentrated set of
purpose-built, structured formulas is clearly harder, however. These are
mostly UNSAT formulas whose encodings conceal a global counting, equivalence,
or parity contradiction from ordinary CDCL reasoning.

The most interesting apples-to-apples comparator is satisfiable SGen. One
180-variable/432-clause SGen formula took 14.43 s here, slightly longer than
either champion under the identical portfolio and machine.

| Formula | Variables/clauses | Five-run portfolio median |
|---|---:|---:|
| `champ_MultiScaleCMA_kcnf_gt1s2L.cnf` | 200/1,000 | 12.47 s |
| `champ_TripleCMA_mpfx_gt1s2L.cnf` | 200/889 | 11.63 s |

## Corpus and protocol

- Source: the official [Global Benchmark Database](https://benchmark-database.de/)
  metadata and CNF snapshots, which aggregate the SAT Competition archive.
- Selection: every unique normalized formula assigned to an actual competition
  track, excluding mere `submissions_*` pools, with its DIMACS header verified
  to have at most 200 variables and 1,000 clauses.
- Corpus: 498 formulas from competition tracks spanning 2002--2025.
- Machine: AMD Ryzen 5 8600G. Both the competition corpus and the two attached
  Nevergrad champion CNFs were measured here.
- Objective: the exact paper portfolio: MiniSat 2.2,
  BreakID+CaDiCaL 1.9.5, and CryptoMiniSat; first finishing branch by process
  CPU time; BreakID preprocessing excluded and replaced by the paper's flat
  8 ms charge.
- Champion remeasurement: five sequential portfolio evaluations per attached
  CNF, aggregated by the median. The individual values are in
  `results/champions-portfolio.json`.
- The full corpus was screened once with a 12 s censoring cap. Recent Main
  Track formulas were screened at 20 s. Selected representatives were then
  measured solver by solver at 30 or 60 s.
- Kissat is reported only as context, as in the paper. March was unavailable on
  this machine and is not treated as a timeout.

This remains a rough external-position study because the full corpus was
screened once with censoring and only selected competition instances received
longer component-level runs. The primary portfolio comparison itself is now
same-machine.

## Full size-bounded archive

| Current-machine portfolio time | Formulas | Interpretation |
|---|---:|---|
| <0.1 s | 322 | trivial for this portfolio |
| 0.1--1 s | 36 | far easier than the champions |
| 1--8 s | 27 | clearly easier |
| 8--11.63 s | 3 | still strictly below the lower champion time |
| >=12 s (censored) | 110 | comparable-or-harder candidates; longer run needed |

Thus 388/498 (77.9%) are definitely easier than the 11.63 s champion. All 110
censored formulas come from only seven families:

| Family | >=12 s / all in family |
|---|---:|
| SGen | 61 / 77 |
| hidden-weighted-bit/circuit miters | 27 / 35 |
| subset cardinality | 10 / 10 |
| PMG (`long-learned-clauses` in GBD) | 6 / 7 |
| HGen | 3 / 16 |
| balanced SGen | 2 / 2 |
| pigeonhole/perfect-matching variants | 1 / 15 |

Among formulas whose GBD status is known, only 5 of 106 satisfiable formulas
hit 12 s, and all five are SGen. The archive also has 87 formulas whose stored
GBD status is `unknown`, so the corpus-wide SAT/UNSAT split should not be
overinterpreted.

## What would have made the result weak?

Saying that it is reasonable to lose to SGen or subset cardinality needs an
explicit counterfactual. For the claim actually made by the experiment---that
generic black-box search can create solver-relative hard instances---the result
would have been weak if any of the following had happened:

1. **Same-domain random controls were competitive.** A uniform phase-transition
   formula at the same 200-variable scale takes 0.99 s, and the strongest
   budget-matched random control takes 0.49 s on the paper's former reference
   machine. These controls still need same-machine remeasurement before a
   precise ratio is quoted.
2. **Routine competition families regularly beat the champions.** If ordinary
   graph-coloring, planning, routing, hardware, or puzzle encodings of equal or
   smaller CNF size routinely took longer, the champions would merely occupy
   the broad middle of the archive. They do not.
3. **A one-solver textbook pathology defeated the portfolio.** Canonical
   pigeonhole, Tseitin, and XOR-chain formulas can be hard for a particular
   CDCL solver, but the point of the portfolio is that another branch recognizes
   or preprocesses their structure. If those formulas had remained harder than
   the champions under the *minimum* over all three branches, the portfolio
   objective would have failed at its intended role.
4. **The result were presented as solver-independent hardness.** It is not. The
   context columns in the paper show March solving the two champions in 0.44
   and 0.65 s, and Kissat in 9.3 and 10.2 s. The favorable comparison is about
   the stated MiniSat/BreakID+CaDiCaL/CryptoMiniSat portfolio. A claim about the
   virtual best over a broader solver set would be weak.

The stronger competition formulas therefore matter in two ways. They set a
real upper frontier that the search did not reach, but they do not erase the
large gap to random controls and routine benchmark families. They are the
output of dedicated constructions designed around proof complexity, hidden
cardinality, circuit equivalence, or parity; the Nevergrad search was not given
those semantic building blocks.

## Families below the champions and how they differ

The table reports every populous family below the champions, plus the easy
members of families that also contain hard formulas. The maximum is over
formulas that finished below the 12 s screening cap.

| Family | Below 12 s | Maximum | Main difference from the champions |
|---|---:|---:|---|
| Tseitin | 158/158 | 2.69 s | Global parity is explicit enough for a portfolio branch; strong against plain resolution, not against this portfolio. |
| Graph coloring | 55/55 | 0.021 s | Local graph constraints and at-most-one structure give strong propagation/preprocessing. |
| XOR chains | 35/35 | 0.008 s | Algebraic structure is exactly what CryptoMiniSat is intended to exploit. |
| Historical random | 30/30 | 2.24 s | Under the 1,000-clause cap these have only 20--60 variables and are much denser than the 200-variable champions. |
| Battleship | 15/15 | 1.73 s | Puzzle/CSP encoding with local propagation; not selected for portfolio hardness. |
| Canonical or easy pigeonhole | 14/15 | 0.090 s | BreakID/cardinality recognition collapses the canonical encoding; only the perturbed perfect-matching variant survives. |
| Planted random | 5/5 | 0.084 s | A planted witness biases the satisfiable search and does not create a hard global refutation. |
| FPGA routing | 6/6 | 0.021 s | Application encoding with auxiliary/local constraints, easy at this small scale. |
| Planning | 10/10 | 0.008 s | Small bounded encoding with abundant deterministic propagation. |
| Easy HGen members | 13/16 | 0.97 s | Same generator label is not sufficient; seed, scale, and satisfiability determine whether its anti-local structure becomes hard. |
| Easy SGen members | 16/77 | 7.95 s | Different group parameters and SAT/UNSAT constructions; some expose a winning portfolio branch. |
| Easy miters | 8/35 | 11.29 s | Circuit topology and the encoded equivalence determine whether gate-level structure remains hidden. |

This comparison also identifies what is distinctive about the champions. They
are full-scale, nearly pure 3-CNF formulas (200 variables and 889--1,000
clauses), close to the random 3-SAT transition, but without the explicit XOR,
cardinality, gate, or local-CSP signatures that let a portfolio member win
immediately. Their achievement is avoiding all three portfolio escape routes
simultaneously for about twelve seconds. It is not universal resistance to SAT
technology.

## Recent Main Track cut

There are 26 unique formulas under the size limit that were selected for a
Main Track from 2017 through 2025. Some are older crafted formulas selected
again in a later Main Track; "recent Main" does not mean newly generated.

- 11/26 were still unsolved at 20 s and are above both champions.
- 4/26 lie in the 11.63--20 s comparison band.
- 11/26 finish below 11.63 s.

The gray band consists of one balanced-SGen UNSAT formula (18.58 s), two
satisfiable SGen formulas (13.35 and 14.18 s in the screen), and a
pigeonhole/perfect-matching variant (11.78 s). Every formula censored at 20 s
is UNSAT.

## Representative hard families

| Formula | v/c | Status | Paper portfolio | Kissat context | What it is |
|---|---:|---:|---:|---:|---|
| `s81-100` | 81/172 | UNSAT | >60 s | >60 s | classic SGen counting contradiction |
| `sgen1-sat-180-100` | 180/432 | SAT | 14.43 s | >30 s | planted, cross-partition exact-choice problem |
| `fixedbandwidth-eq-31` | 125/510 | UNSAT | >30 s | >30 s | subset-cardinality contradiction |
| `hwb-n24-02` | 162/774 | UNSAT | >30 s | >30 s | equivalence miter for hidden weighted bit |
| `pmg-12-UNSAT` | 190/632 | UNSAT | >30 s | >30 s | parity-rich PMG construction |
| `hgen8-n180-03` | 180/280 | UNSAT | 24.36 s | 10.55 s | deliberately hard random HGen formula |
| `mp1-bsat192-689` | 192/689 | UNSAT | >30 s | >30 s | weakened/balanced SGen construction |
| `php12e12` | 156/937 | UNSAT | 12.04 s | >30 s | noncanonical pigeonhole/perfect-matching encoding |

For every `>30 s` row, MiniSat, BreakID+CaDiCaL, and CryptoMiniSat all hit the
cap; Kissat did too. For `s81-100`, all four hit 60 s. BreakID left that SGen
formula's 172 clauses unchanged, so this is not merely preprocessing overhead.

## What makes the stronger formulas different

### SGen UNSAT: an explicit global counting contradiction

The 81-variable representative consists of 172 monotone 3-clauses: 86 all
positive and 86 all negative. The negative clauses partition the variables
into nineteen groups of four and one group of five and enforce at most two
true variables per group, hence at most 40 true variables overall. A second,
shuffled partition enforces at most 40 false variables. With 81 variables the
two requirements contradict each other. The shuffled overlap hides this
one-line counting proof from clause-level CDCL. This is precisely the design
principle described in Spence's SGen work; later SGen variants weakened the
obvious cardinality constraints specifically to defeat cardinality detectors.

The satisfiable SGen comparator has 360 negative binary clauses and 72 positive
width-5 clauses. They encode an exact choice in one partition and coverage in
two shuffled partitions. This is the closest competition analogue to our
result in overall portfolio time, though the winning solver is different.

Sources: [SGen1 paper record](https://pure.qub.ac.uk/en/publications/sgen1-a-generator-of-small-but-difficult-satisfiability-benchmark/),
[weakening cardinality constraints](https://pureadmin.qub.ac.uk/ws/files/14448749/spence2014_v3.pdf).

### Subset cardinality: proof-complexity hardness

Subset-cardinality formulas put a Boolean variable on every edge of a nearly
4-regular bipartite graph. One side requires at least half of its incident
edges to be selected, while the other side requires at most half. The extra
edge makes the global counts inconsistent. On expander-like graphs these
formulas have known long resolution proofs, directly targeting the proof
system underlying CDCL solvers. The representative here has 125 variables and
510 clauses and times out every tested solver branch.

Source: [Miksa and Nordstrom, *Long Proofs of (Seemingly) Simple Formulas*](https://www.csc.kth.se/~miksa/papers/LongProofs_SAT.pdf).

### Hidden-weighted-bit miters: high-level equivalence hidden by CNF

The hard Stanion miters combine two circuits computing the hidden weighted bit
function and ask whether their outputs can differ. They are UNSAT because the
circuits are equivalent, but the useful high-level equivalences are obscured
by the gate-level CNF. Dedicated extraction of propositional structure has
been shown to solve instances that generic CDCL could not. Our 162/774
representative times out all four tested solvers at 30 s.

Source: [Chen, *Exploiting Dynamically Propositional Logic Structures in SAT*](https://arxiv.org/abs/1106.1370).

### PMG: hidden parity/nonlinear structure

The 190/632 representative is the old `pmg-12-UNSAT` formula submitted by Klas
Markstrom. It contains 630 ternary and two binary clauses. Work that recovers
XOR factors from its CNF reports a dramatic collapse in solving time, whereas
ordinary clause-level CryptoMiniSat remains slow. In our unmodified portfolio,
all branches exceed 30 s. This is another case where the hard part is a compact
global algebraic contradiction not exposed in the input language.

Sources: [GBD Main 2023 entry](https://benchmark-database.de/?track=main_2023),
[XOR-factor experiment](https://etd.ohiolink.edu/acprod/odb_etd/ws/send_file/send?accession=ucin1353343116&disposition=inline).

### HGen and modified pigeonhole: solver-fragility tests

HGen is a synthetic random family deliberately developed to produce small hard
formulas; the exact `hgen8-n180-03` instance in this study was already a SAT
2003 benchmark. It needs about 24--25 s in the paper portfolio but only 10.55 s
in Kissat, a clean demonstration that hardness is solver-relative.

The 156/937 pigeonhole formula is not the canonical PHP row in our paper. It is
a Reeves perfect-matching variant. Such variants randomize the graph and mix
cardinality encodings specifically because small changes can defeat the
special-case techniques that make canonical pigeonhole formulas trivial. That
explains why our paper's PHP instance is solved by BreakID in 9 ms while this
competition formula takes about 12 s in the same portfolio.

Sources: [Hirsch's benchmark history](https://edwardahirsch.github.io/edwardahirsch/sat.html),
[bipartite perfect-matching benchmarks](https://www.cs.cmu.edu/~jereeves/research/bipart-paper.pdf).

## Interpretation for the paper

A claim I would be comfortable defending is:

> At the same 200-variable scale, the generated champions are substantially
> harder for the target portfolio than most historical SAT Competition
> formulas of comparable CNF size, and lie in the same runtime range as the
> hard satisfiable SGen examples. They do not match the strongest specialized
> UNSAT constructions, whose encodings deliberately conceal global
> cardinality, equivalence, or parity contradictions and remain resistant to
> every portfolio branch.

The scientifically interesting point is not that black-box search rediscovered
the absolute hardest known small SAT formula. It is that a generic black-box
search over a broad 3-CNF representation, with no hand-coded counting or
circuit semantics, reached the competitive band and found a different solver
profile from the classic generators.

## Reproduction artifacts

- `manifest.csv`: selected formulas and GBD metadata
- `prepare_corpus.py`: official-database query, download, and DIMACS validation
- `benchmark_portfolio.py`: exact portfolio screen
- `remeasure_top.py`: solver-by-solver representative remeasurement
- `summarize_results.py`: aggregate calculation
- `results/aggregate.json`: machine-readable summary
- `results/main_tracks_cap20.json`: recent-Main cut
- `results/exact_*.json`: exact representative measurements
