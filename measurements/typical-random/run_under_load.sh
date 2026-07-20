#!/bin/bash
# Replicates the rebench campaign's four-core load regime
# (keep_four_core_load.py): fillers on CPUs 2-4, measurement on CPU 1.
cd "$(dirname "$0")"
for c in 2 3 4; do taskset -c $c sha256sum /dev/zero & echo $! >> fillers.pid; done
( while true; do
    awk -F: '/MHz/ {gsub(/ /,"",$2); printf "%s,", $2} END {print ""}' /proc/cpuinfo \
      | sed "s/^/$(date -u +%s),/" >> cpu-frequency.csv
    sleep 5
  done ) & echo $! >> fillers.pid
taskset -c 1 python3 typical_random.py sat    > sat.log 2>&1
taskset -c 1 python3 typical_random.py npfs8  > npfs8.log 2>&1
taskset -c 1 python3 typical_random.py npfs10 > npfs10.log 2>&1
while read p; do kill "$p" 2>/dev/null; done < fillers.pid
rm -f fillers.pid
echo LOAD-RUN-COMPLETE
