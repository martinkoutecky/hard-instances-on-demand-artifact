#!/usr/bin/env bash
# Top-level entry point for the ALENEX 2027 artifact "Hard Instances on Demand".
#
#   ./runme.sh              verification pass, no solver runs   (~1 minute)
#   ./runme.sh --smoke      + one small solve per suite         (minutes)
#   ./runme.sh --full       + the complete remeasurement        (many hours)
#
# The default pass is the one to start with: it checks the environment, checks
# the shipped inventory, re-verifies every instance file against the sha256
# recorded when it was measured, and then recomputes the paper's aggregate
# tables from the committed measurement files using the same aggregation code
# that produced the published numbers.  Output lands in runme_out/.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${HERE}"
OUT="${HERE}/runme_out"
mkdir -p "${OUT}"

MODE="default"
case "${1:-}" in
  "")       ;;
  --smoke)  MODE="smoke" ;;
  --full)   MODE="full" ;;
  -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
esac

hr() { printf '\n=== %s %s\n' "$1" "$(printf '=%.0s' $(seq 1 $((70 - ${#1}))))"; }

hr "Step 1/4  environment"
python3 - <<'PY'
import importlib.util, os, shutil, sys
print(f"python            {sys.version.split()[0]}  ({sys.executable})")
for module, needed_for in [
    ("numpy", "searches, measurement"),
    ("nevergrad", "running new searches"),
    ("pysat", "SAT measurement (python-sat)"),
    ("pycryptosat", "SAT measurement (cryptominisat branch)"),
    ("ortools", "flow-shop CP-SAT arm"),
]:
    found = importlib.util.find_spec(module) is not None
    print(f"  {'OK     ' if found else 'MISSING'} {module:<14} {needed_for}")
for binary, needed_for in [
    ("concorde", "TSP / Hamiltonian-cycle suites"),
    ("linkern", "TSP heuristic (optional)"),
]:
    path = shutil.which(binary)
    print(f"  {'OK     ' if path else 'MISSING'} {binary:<14} {needed_for}"
          + (f"  [{path}]" if path else ""))
cpopt = os.environ.get("CPOPT_EXECFILE")
ok = bool(cpopt) and os.path.isfile(cpopt) and not cpopt.startswith("<")
print(f"  {'OK     ' if ok else 'MISSING'} CPOPT_EXECFILE flow-shop CP Optimizer arm"
      + (f"  [{cpopt}]" if cpopt else "  (unset)"))
print("\nMissing entries only limit which suites can be re-measured;"
      "\nsteps 2-4 below need none of them.")
PY

hr "Step 2/4  shipped inventory"
python3 alenex/validate_manifest.py

hr "Step 3/4  instance integrity"
python3 verify_hashes.py

hr "Step 4/4  paper tables, recomputed from committed measurements"
python3 report_tables.py --json "${OUT}/tables.json" | tee "${OUT}/tables.txt"
echo
echo "Wrote ${OUT}/tables.txt and ${OUT}/tables.json"
echo "Map each row to its table in the paper with:"
echo "  current_machine_rebench/CURRENT-MACHINE-PAPER-NUMBERS.md"

if [[ "${MODE}" == "default" ]]; then
  echo
  echo "Done (no solver was run).  Next: ./runme.sh --smoke to validate the"
  echo "solver toolchain, or ./runme.sh --full for the complete campaign."
  exit 0
fi

hr "Step 5  smoke solve (one small case per suite)"
python3 -u current_machine_rebench/run_rebench.py \
  --smoke --output "${OUT}/smoke.json" --suite sat --suite npfs
echo "Smoke results in ${OUT}/smoke.json."
echo "NOTE: smoke runs are dependency validation only and are deliberately NOT"
echo "comparable to the paper's numbers (see the 'Do not use' list in"
echo "current_machine_rebench/CURRENT-MACHINE-PAPER-NUMBERS.md)."

if [[ "${MODE}" == "smoke" ]]; then
  exit 0
fi

hr "Step 6  full remeasurement (hours; needs every dependency above)"
current_machine_rebench/run_all.sh
