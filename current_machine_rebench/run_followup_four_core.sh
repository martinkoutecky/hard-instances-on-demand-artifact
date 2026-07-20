#!/usr/bin/env bash
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY="$(cd "${HERE}/.." && pwd)"
OUTPUT_ROOT="${1:-${HERE}/results/followup-four-core}"
EXTERNAL_DIR="${HERE}/results/external"
PYTHON="${PYTHON:-python3}"
RESTART_DELAY="${REBENCH_RESTART_DELAY:-15}"

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export BLIS_NUM_THREADS=1
export CPOPT_EXECFILE="${CPOPT_EXECFILE:-<software>/CPLEX_Studio222/cpoptimizer/bin/x86-64_linux/cpoptimizer}"

mkdir -p "${OUTPUT_ROOT}"
exec 9>"${OUTPUT_ROOT}/campaign.lock"
if ! flock -n 9; then
  echo "$(date -u --iso-8601=seconds) follow-up supervisor refused: lock held"
  exit 2
fi

run_retry() {
  local cpu="$1"
  local name="$2"
  shift 2
  local attempt=0
  while true; do
    attempt=$((attempt + 1))
    echo "$(date -u --iso-8601=seconds) START ${name} cpu=${cpu} attempt=${attempt}"
    taskset -c "${cpu}" "$@"
    local status=$?
    if [[ "${status}" == "0" ]]; then
      echo "$(date -u --iso-8601=seconds) DONE ${name} cpu=${cpu}"
      return 0
    fi
    echo "$(date -u --iso-8601=seconds) RETRY ${name} cpu=${cpu} status=${status} in ${RESTART_DELAY}s"
    sleep "${RESTART_DELAY}"
  done
}

tsp_shard() {
  local cpu="$1"
  local shard="$2"
  run_retry "${cpu}" "tsp-random-screen-${shard}" \
    "${PYTHON}" -u "${HERE}/followup_rebench.py" tsp-random-shard \
    --budget 100000 --seed 20260601 --keep 20 --shard-count 8 \
    --shard-index "${shard}" \
    --output "${OUTPUT_ROOT}/tsp-random-screen-shard${shard}.json"
}

frequency_pid=""
cleanup() {
  if [[ -n "${frequency_pid}" ]]; then
    kill "${frequency_pid}" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "$(date -u --iso-8601=seconds) FOLLOWUP START repository=${REPOSITORY} output=${OUTPUT_ROOT}"
taskset -c 11 "${PYTHON}" -u "${HERE}/monitor_cpu_frequency.py" \
  --output "${OUTPUT_ROOT}/cpu-frequency.csv" \
  >"${OUTPUT_ROOT}/frequency-monitor.log" 2>&1 &
frequency_pid=$!
echo "${frequency_pid}" >"${OUTPUT_ROOT}/frequency-monitor.pid"

(
  run_retry 1 npfs8-control \
    "${PYTHON}" -u "${HERE}/followup_rebench.py" npfs8-control \
    --budget 100000 --seed 20260601 --keep 20 \
    --output "${OUTPUT_ROOT}/npfs8-control.json"
  tsp_shard 1 3
  tsp_shard 1 7
) >"${OUTPUT_ROOT}/lane-cpu1.log" 2>&1 &
lane1=$!

(
  tsp_shard 2 0
  tsp_shard 2 4
  run_retry 2 tsp-20009-half0 \
    "${PYTHON}" -u "${HERE}/followup_rebench.py" tsp-fixed \
    --case 20009_hard --external-dir "${EXTERNAL_DIR}" \
    --shard-count 2 --shard-index 0 \
    --output "${OUTPUT_ROOT}/tsp-20009-half0.json"
) >"${OUTPUT_ROOT}/lane-cpu2.log" 2>&1 &
lane2=$!

(
  run_retry 3 ham-full-r3 \
    "${PYTHON}" -u "${HERE}/run_rebench.py" --suite ham \
    --concorde-train-repeats 3 --concorde-heldout-repeats 3 \
    --output "${OUTPUT_ROOT}/ham-full-r3.json"
  run_retry 3 tsp-gr229 \
    "${PYTHON}" -u "${HERE}/followup_rebench.py" tsp-fixed \
    --case gr229 --external-dir "${EXTERNAL_DIR}" \
    --output "${OUTPUT_ROOT}/tsp-gr229.json"
  tsp_shard 3 2
  tsp_shard 3 6
  run_retry 3 tsp-20009-half1 \
    "${PYTHON}" -u "${HERE}/followup_rebench.py" tsp-fixed \
    --case 20009_hard --external-dir "${EXTERNAL_DIR}" \
    --shard-count 2 --shard-index 1 \
    --output "${OUTPUT_ROOT}/tsp-20009-half1.json"
) >"${OUTPUT_ROOT}/lane-cpu3.log" 2>&1 &
lane3=$!

(
  run_retry 4 tsp-full-r3 \
    "${PYTHON}" -u "${HERE}/run_rebench.py" --suite tsp \
    --concorde-train-repeats 3 --concorde-heldout-repeats 3 \
    --output "${OUTPUT_ROOT}/tsp-full-r3.json"
  tsp_shard 4 1
  tsp_shard 4 5
) >"${OUTPUT_ROOT}/lane-cpu4.log" 2>&1 &
lane4=$!

wait "${lane1}" "${lane2}" "${lane3}" "${lane4}"
echo "$(date -u --iso-8601=seconds) SCREEN/HEADLINE PHASE DONE"

shards=()
for shard in 0 1 2 3 4 5 6 7; do
  shards+=("${OUTPUT_ROOT}/tsp-random-screen-shard${shard}.json")
done
"${PYTHON}" -u "${HERE}/followup_rebench.py" tsp-random-prepare \
  --shards "${shards[@]}" --keep 20 \
  --output "${OUTPUT_ROOT}/tsp-random-candidates.json"

remeasure_pids=()
for shard in 0 1 2 3; do
  cpu=$((shard + 1))
  (
    run_retry "${cpu}" "tsp-random-clean-${shard}" \
      "${PYTHON}" -u "${HERE}/followup_rebench.py" tsp-random-remeasure \
      --candidates "${OUTPUT_ROOT}/tsp-random-candidates.json" \
      --shard-count 4 --shard-index "${shard}" \
      --output "${OUTPUT_ROOT}/tsp-random-clean-shard${shard}.json"
  ) >"${OUTPUT_ROOT}/remeasure-cpu${cpu}.log" 2>&1 &
  remeasure_pids+=("$!")
done
wait "${remeasure_pids[@]}"

clean_shards=()
for shard in 0 1 2 3; do
  clean_shards+=("${OUTPUT_ROOT}/tsp-random-clean-shard${shard}.json")
done
"${PYTHON}" -u "${HERE}/followup_rebench.py" tsp-random-finalize \
  --candidates "${OUTPUT_ROOT}/tsp-random-candidates.json" \
  --remeasure "${clean_shards[@]}" \
  --output "${OUTPUT_ROOT}/tsp-random-final.json"

"${PYTHON}" -u "${HERE}/followup_rebench.py" tsp-fixed-finalize \
  --shards "${OUTPUT_ROOT}/tsp-20009-half0.json" "${OUTPUT_ROOT}/tsp-20009-half1.json" \
  --output "${OUTPUT_ROOT}/tsp-20009.json"

date -u --iso-8601=seconds >"${OUTPUT_ROOT}/COMPLETED"
echo "$(date -u --iso-8601=seconds) FOLLOWUP COMPLETE"
