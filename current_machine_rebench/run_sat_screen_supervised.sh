#!/usr/bin/env bash
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CPU="${1:?logical CPU is required}"
PORTFOLIO="${2:?portfolio is required}"
ENCODING="${3:?encoding is required}"
OUTPUT_DIR="${4:-${HERE}/results/sat_randomsearch}"
RESTART_DELAY="${REBENCH_RESTART_DELAY:-30}"
MAX_RESTARTS="${REBENCH_MAX_RESTARTS:-20}"

attempt=0
while true; do
  attempt=$((attempt + 1))
  echo "$(date -u --iso-8601=seconds) ${PORTFOLIO}_${ENCODING} supervisor launch attempt ${attempt}"
  taskset -c "${CPU}" python3 -u "${HERE}/sat_randomsearch.py" \
    --portfolio "${PORTFOLIO}" --encoding "${ENCODING}" \
    --output-dir "${OUTPUT_DIR}"
  status=$?
  if [[ "${status}" == "0" ]]; then
    echo "$(date -u --iso-8601=seconds) ${PORTFOLIO}_${ENCODING} screen completed"
    exit 0
  fi
  if (( attempt >= MAX_RESTARTS )); then
    echo "$(date -u --iso-8601=seconds) ${PORTFOLIO}_${ENCODING} supervisor giving up after ${attempt} attempts (status ${status})"
    exit "${status}"
  fi
  echo "$(date -u --iso-8601=seconds) ${PORTFOLIO}_${ENCODING} attempt ${attempt} failed with status ${status}; restarting in ${RESTART_DELAY}s"
  sleep "${RESTART_DELAY}"
done
