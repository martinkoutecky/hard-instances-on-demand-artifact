#!/usr/bin/env bash
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CPU="${1:?usage: run_domain_suite_supervised.sh CPU tsp|ham [OUTPUT_ROOT]}"
DOMAIN="${2:?usage: run_domain_suite_supervised.sh CPU tsp|ham [OUTPUT_ROOT]}"
OUTPUT_ROOT="${3:-${HERE}/results}"
EXTERNAL_DIR="${OUTPUT_ROOT}/external"
RESTART_DELAY="${REBENCH_RESTART_DELAY:-30}"
MAX_RESTARTS="${REBENCH_MAX_RESTARTS:-20}"
LOCK_FILE="${OUTPUT_ROOT}/${DOMAIN}-suite.lock"
OUTPUT="${OUTPUT_ROOT}/${DOMAIN}-suite.json"

case "${DOMAIN}" in
  tsp)
    SUITES=(--suite tsp --suite tsp_external)
    ;;
  ham)
    SUITES=(--suite ham --suite ham_external)
    ;;
  *)
    echo "domain must be tsp or ham, got: ${DOMAIN}" >&2
    exit 2
    ;;
esac

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export BLIS_NUM_THREADS=1

mkdir -p "${OUTPUT_ROOT}"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "$(date -u --iso-8601=seconds) supervisor refused: ${DOMAIN} lock is held"
  exit 2
fi

attempt=0
while true; do
  attempt=$((attempt + 1))
  echo "$(date -u --iso-8601=seconds) ${DOMAIN} supervisor launch attempt ${attempt}"
  taskset -c "${CPU}" python3 -u "${HERE}/run_rebench.py" \
    "${SUITES[@]}" --output "${OUTPUT}" --external-dir "${EXTERNAL_DIR}"
  status=$?
  if [[ "${status}" == "0" ]]; then
    echo "$(date -u --iso-8601=seconds) ${DOMAIN} supervisor: suite completed"
    exit 0
  fi
  if (( attempt >= MAX_RESTARTS )); then
    echo "$(date -u --iso-8601=seconds) ${DOMAIN} supervisor: giving up after ${attempt} attempts (status ${status})"
    exit "${status}"
  fi
  echo "$(date -u --iso-8601=seconds) ${DOMAIN} supervisor: attempt ${attempt} failed with status ${status}; restarting in ${RESTART_DELAY}s"
  sleep "${RESTART_DELAY}"
done
