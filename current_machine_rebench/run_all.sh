#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY="$(cd "${HERE}/.." && pwd)"
CPU="${1:-1}"
OUTPUT_ROOT="${2:-${HERE}/results}"
RANDOM_DIR="${OUTPUT_ROOT}/sat_randomsearch"
RESULTS_JSON="${OUTPUT_ROOT}/paper_instances.json"
EXTERNAL_DIR="${OUTPUT_ROOT}/external"

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export BLIS_NUM_THREADS=1
export CPOPT_EXECFILE="${CPOPT_EXECFILE:-<software>/CPLEX_Studio222/cpoptimizer/bin/x86-64_linux/cpoptimizer}"

mkdir -p "${OUTPUT_ROOT}" "${RANDOM_DIR}"

taskset -c "${CPU}" python3 -u \
  "${REPOSITORY}/comparisons/external_benchmarks/prepare_instances.py" \
  --output "${EXTERNAL_DIR}"

taskset -c "${CPU}" python3 -u "${HERE}/sat_randomsearch.py" \
  --portfolio original3 --encoding kcnf --output-dir "${RANDOM_DIR}"

# The recovered mprefix control is a 15k Stage-1 candidate, not the 100k paper
# control. Regenerate both encodings under one explicit protocol.
taskset -c "${CPU}" python3 -u "${HERE}/sat_randomsearch.py" \
  --portfolio original3 --encoding mprefix --output-dir "${RANDOM_DIR}"

# Optional evidence needed before putting the four-solver escalation in the
# paper as more than a transfer check. This is off by default because it adds
# another full 100k search. Set RUN_DPLL4_RANDOMSEARCH=1 to enable it.
if [[ "${RUN_DPLL4_RANDOMSEARCH:-0}" == "1" ]]; then
  taskset -c "${CPU}" python3 -u "${HERE}/sat_randomsearch.py" \
    --portfolio dpll4 --encoding mprefix --output-dir "${RANDOM_DIR}"
fi

# Independently launched domain suites hold these locks while active. Wait for
# them before importing their atomically checkpointed rows into the final report.
flock "${OUTPUT_ROOT}/tsp-suite.lock" true
flock "${OUTPUT_ROOT}/ham-suite.lock" true

taskset -c "${CPU}" python3 -u "${HERE}/run_rebench.py" \
  --output "${RESULTS_JSON}" --randomsearch-dir "${RANDOM_DIR}" \
  --external-dir "${EXTERNAL_DIR}" \
  --import-checkpoint "${OUTPUT_ROOT}/tsp-suite.json" \
  --import-checkpoint "${OUTPUT_ROOT}/ham-suite.json"

echo "Completed campaign at repository ${REPOSITORY}"
echo "Results: ${RESULTS_JSON}"
