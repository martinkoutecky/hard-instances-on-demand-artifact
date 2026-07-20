#!/bin/bash
# Same four-core load regime as notes/typical-random: fillers on CPUs 2-4,
# measurement on CPU 1, frequency log every 5 s.
cd "$(dirname "$0")"
for c in 2 3 4; do taskset -c $c sha256sum /dev/zero & echo $! >> fillers.pid; done
( while true; do
    awk -F: '/MHz/ {gsub(/ /,"",$2); printf "%s,", $2} END {print ""}' /proc/cpuinfo \
      | sed "s/^/$(date -u +%s),/" >> cpu-frequency.csv
    sleep 5
  done ) & echo $! >> fillers.pid
taskset -c 1 python3 dpll4_remeasure.py champs  > champs.log 2>&1
taskset -c 1 python3 dpll4_remeasure.py typical > typical.log 2>&1
while read p; do kill "$p" 2>/dev/null; done < fillers.pid
rm -f fillers.pid
echo LOAD-RUN-COMPLETE
