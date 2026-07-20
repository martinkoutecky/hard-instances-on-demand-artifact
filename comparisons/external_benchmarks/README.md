# External benchmark package

This package prepares the classical-family external SAT, TSP, and HAM
comparisons used by the paper. The broader SAT Competition comparison remains
separately packaged under `comparisons/sat_comp/`. Large upstream collections
are downloaded into a run-local cache rather than duplicated in Git.
`manifest.json` pins each archive by SHA-256 (and the Hard-TSPLIB source
commit); `prepare_instances.py` verifies the archives, extracts the paper
subsets, generates the deterministic families, and writes a per-instance
checksum manifest.

```bash
python3 comparisons/external_benchmarks/prepare_instances.py \
  --output current_machine_rebench/results/external
```

The current-machine campaign calls this step automatically. Prepared files and
download caches belong under the ignored campaign result directory.

## Selection boundary

- **TSPLIB:** the literal documented selector, every `TYPE:TSP` instance with
  dimension at most 300 (58 files in the official archive). The missing
  historical raw log does not let us prove whether the former 0.090 s median
  used all 58 or excluded the three instances below 20 vertices, so the new
  campaign makes the membership explicit and recomputes it.
- **Hard-TSPLIB:** all 40 files actually shipped by the authors at commit
  `74b142a`. The upstream README says 41, but that checkout contains 40.
- **FHCP:** `graph5.hcp` through `graph15.hcp`, the exact 90--150 vertex slice
  underlying the paper row.
- **Clustered Euclidean:** twelve instances regenerated from the authors' local
  benchmark generator. These are not recovered files from van Hemert. The
  campaign therefore calls this family `clustered_euclidean`, preserving the
  experiment while avoiding false provenance.
- **SAT families:** canonical PHP(12,11), W(2;3,13), and a pinned
  150-variable/400-clause Tseitin representative from the Global Benchmark
  Database (`144799...`). The missing historical script and graph prevent an
  exact reconstruction, so this is a fresh replacement comparator with the
  same dimensions, not a claim about the vanished file's identity. The
  phase-transition row is already the recovered
  `todo_instances/sat/phase_transition.cnf` case in the main campaign.

Classical TSPLIB instances are passed unmodified to Concorde's native TSPLIB
reader; in particular, `gr229` uses GEO coordinates and must not be converted
through the generated-matrix parser. Every Concorde call runs in a fresh capped
child process.
