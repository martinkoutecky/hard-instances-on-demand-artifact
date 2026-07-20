# NPFS reference comparisons

All runners in this directory solve the same non-permutation flow-shop model
as the paper: F_m || C_max. Published permutation-flow-shop matrices are used
only as processing-time inputs; their published PFSP bounds and hardness
claims are not transferred.

## Taillard generation

run_external_npfs.py implements Taillard's Park--Miller generator with the
published floating-point unif(1,99) mapping:

~~~text
state = (16807 * state) mod (2^31 - 1)
duration = 1 + floor(99 * state / (2^31 - 1))
~~~

The ten standard 20x5 seeds reproduce the official 20x5 matrices. The
repository's former modulo-based generator did not and is intentionally absent
from this branch.

Taillard did not publish a 10x5 benchmark group. For a controlled same-size
diagnostic, taillard-generator-10x5-cpopt.json applies the exact generator at
10x5 using those ten seeds. These matrices must be described as
Taillard-generator 10x5, not as official Taillard benchmark instances.

On the current AMD Ryzen 5 8600G baseline, all 100 combinations of ten
generated matrices and CP Optimizer seeds 1--10 were proved optimal. Times
ranged from 0.0116 to 0.8047 seconds; the hardest matrix by ten-seed median was
taillard_gen_10x5_05 at 0.6787 seconds. The thesis 10x5 DE champion's
seven-seed median on the same machine was 255.49 seconds. Restricting both
families to solver seeds 1--7, the hardest Taillard-generator matrix has a
0.6676-second median, so the generated champion is about 383 times slower.

## Commands

Set the unrestricted or Community Edition executable explicitly if it is not
on PATH:

~~~bash
export CPOPT_EXECFILE=/path/to/CPLEX_Studio/cpoptimizer/bin/x86-64_linux/cpoptimizer
~~~

Then, from the repository root:

~~~bash
python comparisons/npfs/run_external_npfs.py \
  --suite taillard --taillard-size 10x5 \
  --solver-seeds 1,2,3,4,5,6,7,8,9,10 --time-limit 60 \
  --output /tmp/taillard-generator-10x5.json
~~~

The published 20x5 group uses --taillard-size 20x5. The Demirkol suite is
available with --suite demirkol, but the installed CP Optimizer Community
Edition rejects even its smallest 20x15 instance because of the license's
search-space limit. That is a license failure, not a hardness measurement;
the exact failure is preserved in demirkol-pilot-300s.json.
