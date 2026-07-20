#!/usr/bin/env bash
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CPU="${1:-1}"
OUTPUT_ROOT="${2:-${HERE}/results}"
RESTART_DELAY="${REBENCH_RESTART_DELAY:-30}"
MAX_RESTARTS="${REBENCH_MAX_RESTARTS:-20}"
LOCK_FILE="${OUTPUT_ROOT}/campaign.lock"

mkdir -p "${OUTPUT_ROOT}"
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
  echo "$(date -u --iso-8601=seconds) supervisor refused: campaign lock is held"
  exit 2
fi

attempt=0
while true; do
  attempt=$((attempt + 1))
  echo "$(date -u --iso-8601=seconds) supervisor launch attempt ${attempt}"
  bash "${HERE}/run_all.sh" "${CPU}" "${OUTPUT_ROOT}"
  status=$?
  if [[ "${status}" == "0" ]]; then
    echo "$(date -u --iso-8601=seconds) supervisor: campaign completed"
    exit 0
  fi
  if (( attempt >= MAX_RESTARTS )); then
    echo "$(date -u --iso-8601=seconds) supervisor: giving up after ${attempt} attempts (status ${status})"
    exit "${status}"
  fi
  echo "$(date -u --iso-8601=seconds) supervisor: attempt ${attempt} failed with status ${status}; restarting in ${RESTART_DELAY}s"
  sleep "${RESTART_DELAY}"
done
