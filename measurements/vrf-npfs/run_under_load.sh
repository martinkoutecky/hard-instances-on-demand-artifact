#!/bin/bash
# Official VRF 10x5 instances re-solved under the paper's NPFS model
# (comparisons/vrf_cpopt_10x5/run_cpopt.py -- the same solver model that
# produced the Taillard 20x5 row), seeds 1-10, 60 s cap, measurement on
# CPU 1 under the campaign's four-core load regime (fillers on CPUs 2-4).
cd "$(dirname "$0")"
export CPOPT_EXECFILE="${CPOPT_EXECFILE:-<cpoptimizer>}"
export OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 BLIS_NUM_THREADS=1
for c in 2 3 4; do taskset -c $c sha256sum /dev/zero & echo $! >> fillers.pid; done
( while true; do
    awk -F: '/MHz/ {gsub(/ /,"",$2); printf "%s,", $2} END {print ""}' /proc/cpuinfo \
      | sed "s/^/$(date -u +%s),/" >> cpu-frequency.csv
    sleep 5
  done ) & echo $! >> fillers.pid
VRF=<packet-root>/comparisons/vrf_cpopt_10x5
taskset -c 1 python3 "$VRF/run_cpopt.py" \
  --instances-file "$VRF/instances.json" \
  $(for i in 1 2 3 4 5 6 7 8 9 10; do echo --instance VFR10_5_$i; done) \
  --seeds 1-10 --time-limit 60 \
  --output vrf10x5-official-npfs.json > vrf.log 2>&1
while read p; do kill "$p" 2>/dev/null; done < fillers.pid
rm -f fillers.pid
echo LOAD-RUN-COMPLETE
