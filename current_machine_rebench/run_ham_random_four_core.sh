#!/usr/bin/env bash
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_ROOT="${1:-${HERE}/results/ham-random-four-core}"
PYTHON="${PYTHON:-python3}"
RESTART_DELAY="${REBENCH_RESTART_DELAY:-15}"

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export BLIS_NUM_THREADS=1

mkdir -p "${OUTPUT_ROOT}"
exec 9>"${OUTPUT_ROOT}/campaign.lock"
if ! flock -n 9; then
  echo "$(date -u --iso-8601=seconds) HAM RandomSearch supervisor refused: lock held"
  exit 2
fi

run_retry() {
  local cpu="$1"
  local encoding="$2"
  local attempt=0
  while true; do
    attempt=$((attempt + 1))
    echo "$(date -u --iso-8601=seconds) START ham-random-${encoding} cpu=${cpu} attempt=${attempt}"
    taskset -c "${cpu}" "${PYTHON}" -u "${HERE}/followup_rebench.py" ham-random-control \
      --encoding "${encoding}" --budget 100000 --seed 20260719 --keep 20 \
      --output "${OUTPUT_ROOT}/ham-random-${encoding}.json"
    local status=$?
    if [[ "${status}" == "0" ]]; then
      echo "$(date -u --iso-8601=seconds) DONE ham-random-${encoding} cpu=${cpu}"
      return 0
    fi
    echo "$(date -u --iso-8601=seconds) RETRY ham-random-${encoding} cpu=${cpu} status=${status} in ${RESTART_DELAY}s"
    sleep "${RESTART_DELAY}"
  done
}

frequency_pid=""
keeper_pid=""
cleanup() {
  if [[ -n "${frequency_pid}" ]]; then
    kill "${frequency_pid}" 2>/dev/null || true
  fi
  if [[ -n "${keeper_pid}" ]]; then
    kill "${keeper_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "$(date -u --iso-8601=seconds) HAM RANDOM START output=${OUTPUT_ROOT}"
taskset -c 11 "${PYTHON}" -u "${HERE}/monitor_cpu_frequency.py" \
  --output "${OUTPUT_ROOT}/cpu-frequency.csv" \
  >"${OUTPUT_ROOT}/frequency-monitor.log" 2>&1 &
frequency_pid=$!
echo "${frequency_pid}" >"${OUTPUT_ROOT}/frequency-monitor.pid"

taskset -c 11 "${PYTHON}" -u "${HERE}/keep_four_core_load.py" \
  --campaign-pid "$$" --completed "${OUTPUT_ROOT}/COMPLETED" \
  --log "${OUTPUT_ROOT}/load-keeper.log" \
  >"${OUTPUT_ROOT}/load-keeper-stdout.log" 2>&1 &
keeper_pid=$!
echo "${keeper_pid}" >"${OUTPUT_ROOT}/load-keeper.pid"

run_retry 1 trivial >"${OUTPUT_ROOT}/trivial.log" 2>&1 &
trivial_pid=$!
run_retry 2 perm_int >"${OUTPUT_ROOT}/perm-int.log" 2>&1 &
perm_int_pid=$!
run_retry 3 perm_thr >"${OUTPUT_ROOT}/perm-thr.log" 2>&1 &
perm_thr_pid=$!

wait "${trivial_pid}" "${perm_int_pid}" "${perm_thr_pid}"
date -u --iso-8601=seconds >"${OUTPUT_ROOT}/COMPLETED"
echo "$(date -u --iso-8601=seconds) HAM RANDOM COMPLETE"
