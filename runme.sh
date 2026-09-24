#!/usr/bin/env bash
# Top-level entry point for the ALENEX 2027 artifact "Hard Instances on Demand".
#
#   ./runme.sh                       verification pass, no solver runs  (~1 minute)
#   ./runme.sh --smoke  [--cpu N]    + one small solve per suite        (minutes)
#   ./runme.sh --full   [--cpu N] [--out DIR]
#                                    + the complete remeasurement       (~1 day)
#   ./runme.sh --tables DIR          tables of a finished --full rerun in DIR,
#                                    side by side with the paper's numbers
#
# Every solver run is pinned to the single logical CPU N (default 1) with
# taskset; pick an idle core.  --full writes to DIR (default runme_out/rerun)
# and never into the committed current_machine_rebench/results/.  Re-running
# the same --full command resumes an interrupted campaign.
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
CPU=1
RERUN="${OUT}/rerun"
while (( $# )); do
  case "$1" in
    --smoke)  MODE="smoke" ;;
    --full)   MODE="full" ;;
    --tables) MODE="tables"; RERUN="${2:?--tables needs the rerun directory}"; shift ;;
    --cpu)    CPU="${2:?--cpu needs a CPU number}"; shift ;;
    --out)    RERUN="${2:?--out needs a directory}"; shift ;;
    -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1 (try --help)" >&2; exit 2 ;;
  esac
  shift
done

hr() { printf '\n=== %s %s\n' "$1" "$(printf '=%.0s' $(seq 1 $((70 - ${#1}))))"; }

rerun_tables() {
  local report="${RERUN}/paper_instances.json"
  if ! python3 - "${report}" <<'PY'
import json, sys
try:
    report = json.load(open(sys.argv[1], encoding="utf-8"))
except FileNotFoundError:
    sys.exit(1)
sys.exit(0 if report.get("completed_at") else 1)
PY
  then
    echo "No finished campaign in ${RERUN} (paper_instances.json missing or" >&2
    echo "incomplete).  Re-run the same ./runme.sh --full command to resume it." >&2
    exit 1
  fi
  python3 report_tables.py --report "${report}" --compare \
    --json "${RERUN}/tables.json" | tee "${RERUN}/tables.txt"
  echo
  echo "Wrote ${RERUN}/tables.txt and ${RERUN}/tables.json"
  echo "Map each row to its table in the paper with:"
  echo "  current_machine_rebench/CURRENT-MACHINE-PAPER-NUMBERS.md"
}

if [[ "${MODE}" == "tables" ]]; then
  if [[ ! -d "${RERUN}" ]]; then
    echo "no such directory: ${RERUN}" >&2
    exit 1
  fi
  RERUN="$(cd "${RERUN}" && pwd)"
  rerun_tables
  exit 0
fi

if [[ "${MODE}" != "default" ]]; then
  if ! command -v taskset >/dev/null; then
    echo "taskset (util-linux) is required to pin solver runs to one CPU." >&2
    exit 2
  fi
  if ! taskset -c "${CPU}" true 2>/dev/null; then
    echo "cannot pin to CPU ${CPU}; available: $(taskset -cp $$ | sed 's/.*: //')" >&2
    exit 2
  fi
fi

if [[ "${MODE}" == "full" ]]; then
  mkdir -p "${RERUN}"
  RERUN="$(cd "${RERUN}" && pwd)"
  # The campaign's checkpoints are keyed to the exact repository state (git HEAD
  # plus any modified or untracked files), so the output directory must not show
  # up as a change to the repository itself.
  case "${RERUN}/" in
    "${HERE}/current_machine_rebench/results/"*)
      echo "refusing to write into the committed results; choose another --out" >&2
      exit 2 ;;
    "${HERE}/"*)
      if ! git check-ignore -q "${RERUN}"; then
        echo "--out ${RERUN} is inside the repository but not git-ignored;" >&2
        echo "use a directory under runme_out/ or outside the repository." >&2
        exit 2
      fi ;;
  esac
fi

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
    ("docplex", "flow-shop CP Optimizer arm (modeling layer)"),
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
# Same discovery order as the solver code: CPOPT_EXECFILE, then PATH.
cpopt = os.environ.get("CPOPT_EXECFILE")
if not (cpopt and os.path.isfile(cpopt) and os.access(cpopt, os.X_OK)):
    cpopt = shutil.which("cpoptimizer")
print(f"  {'OK     ' if cpopt else 'MISSING'} cpoptimizer    flow-shop CP Optimizer arm"
      + (f"  [{cpopt}]" if cpopt else "  (see README: IBM CP Optimizer)"))
print("\nMissing entries only limit which suites can be re-measured;"
      "\nsteps 2-4 below need none of them.")
PY
# --full needs every solver; fail now rather than hours into the campaign.
if [[ "${MODE}" == "full" ]]; then
  python3 - <<'PY'
import importlib.util, os, shutil, sys
missing = [m for m in ("numpy", "nevergrad", "pysat", "pycryptosat", "ortools", "docplex")
           if importlib.util.find_spec(m) is None]
if shutil.which("concorde") is None:
    missing.append("concorde")
cpopt = os.environ.get("CPOPT_EXECFILE")
if not (cpopt and os.path.isfile(cpopt) and os.access(cpopt, os.X_OK)) \
        and shutil.which("cpoptimizer") is None:
    missing.append("cpoptimizer")
if missing:
    sys.exit("--full needs every dependency above; missing: " + ", ".join(missing))
PY
fi

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

hr "Step 5  smoke solve on CPU ${CPU} (one small case per suite)"
SUITES=(--suite sat)
# The flow-shop suite needs CP Optimizer for every case (it cross-evaluates
# each instance on both solvers), so run it only when the solver is present.
if python3 -c 'import docplex' 2>/dev/null \
   && { [[ -x "${CPOPT_EXECFILE:-}" ]] || command -v cpoptimizer >/dev/null; }; then
  SUITES+=(--suite npfs)
else
  echo "CP Optimizer not found: skipping the flow-shop (npfs) smoke case."
  echo "See the README section 'IBM CP Optimizer' for the free install."
fi
# A checkpoint left by an older checkout would be refused, so start afresh.
rm -f "${OUT}/smoke.json"
taskset -c "${CPU}" python3 -u current_machine_rebench/run_rebench.py \
  --smoke --output "${OUT}/smoke.json" "${SUITES[@]}"
echo "Smoke results in ${OUT}/smoke.json."
echo "NOTE: smoke runs are dependency validation only and are deliberately NOT"
echo "comparable to the paper's numbers (see the 'Do not use' list in"
echo "current_machine_rebench/CURRENT-MACHINE-PAPER-NUMBERS.md)."

if [[ "${MODE}" == "smoke" ]]; then
  exit 0
fi

hr "Step 6  full remeasurement on CPU ${CPU}"
if [[ -n "$(git status --porcelain)" ]]; then
  echo "WARNING: the working tree differs from the checked-out commit (see"
  echo "git status).  The differences become part of the campaign's revision"
  echo "stamp.  If they are unintended (e.g. files overwritten by an earlier run"
  echo "of run_all.sh), restore them first:  git checkout -- ."
fi
echo "Output:  ${RERUN}"
echo "Started: $(date)"
echo "This is a serial campaign of roughly a day on one core.  If it is"
echo "interrupted, re-run the same command to resume where it stopped."
current_machine_rebench/run_all.sh "${CPU}" "${RERUN}"

hr "Step 7  paper tables from this rerun, next to the paper's numbers"
rerun_tables
