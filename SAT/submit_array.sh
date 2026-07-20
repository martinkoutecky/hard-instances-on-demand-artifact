#!/usr/bin/env bash
# Submit each master SAT config as ONE SLURM job array. divide.py expands
# master -> divided/<base>/conf{0..M-1}.json (one per (opt, iter)), then a
# single
#   sbatch --array=0-(M-1)%K --wrap='cd SAT && [SAT_PORTFOLIO4=1] python3 exp.py --file <divided>/conf$SLURM_ARRAY_TASK_ID.json'
# is submitted per master.
#
# SAT_PORTFOLIO4 gating is AUTOMATIC: any master whose name contains "dpll4"
# gets SAT_PORTFOLIO4=1 in its wrap (the 4-solver paradigm-robust portfolio);
# everything else runs the canonical 3-solver portfolio. This prevents the
# silent-poisoning failure where dpll4 configs run against the wrong objective.
#
# Adapted from Ham/submit_array.sh; defaults tuned for the dpll4f ffa runs
# (6 cpus: parent + 4 branch children + short-lived breakid; 11:55 fits ffa's
# MaxTime=12h -- hot cells will TIMEOUT-truncate, which is normal for
# hardness search: recorded evals are genuine, best is a floor).

CPUS=6
TIME="11:55:00"
PARTITION=""
MEM=""
CONC=25
DRY_RUN=0
YES=0

usage() {
    cat <<EOF
Usage: $0 [options] <master_cfg1.json> [<master_cfg2.json> ...]

Options:
  -c CPUS         --cpus-per-task per task  (default $CPUS)
  -t TIME         --time HH:MM:SS per task  (default $TIME)
  -p PARTITION    --partition               (default: cluster default)
  -m MEM          --mem, e.g. 32G           (default: cluster default)
  -k CONC         max concurrent array tasks per master (default $CONC)
  -n              dry run -- divide but don't sbatch
  -y              skip confirmation
  -h              this help

For each master config, runs divide.py to split it into per-(opt, iter)
sub-configs, then submits ONE sbatch --array per master. Sub-configs
land in SAT/divided/<base>/conf{0..N-1}.json.
EOF
}

while getopts ":c:t:p:m:k:nyh" opt; do
    case "$opt" in
        c) CPUS="$OPTARG" ;;
        t) TIME="$OPTARG" ;;
        p) PARTITION="$OPTARG" ;;
        m) MEM="$OPTARG" ;;
        k) CONC="$OPTARG" ;;
        n) DRY_RUN=1 ;;
        y) YES=1 ;;
        h) usage; exit 0 ;;
        \?) echo "Unknown option -$OPTARG" >&2; usage; exit 1 ;;
        :)  echo "Option -$OPTARG requires arg" >&2; usage; exit 1 ;;
    esac
done
shift $((OPTIND - 1))

[[ $# -eq 0 ]] && { usage; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SAT_DIR="$SCRIPT_DIR"
DIVIDE_PY="$ROOT_DIR/divide.py"
VENV_PYTHON="$ROOT_DIR/venv/bin/python3"

[[ -x "$VENV_PYTHON" ]] || { echo "[X] no venv at $VENV_PYTHON" >&2; exit 1; }
[[ -f "$DIVIDE_PY"   ]] || { echo "[X] no divide.py at $DIVIDE_PY" >&2; exit 1; }

mkdir -p "$SAT_DIR/logs" "$SAT_DIR/divided"

declare -a array_specs   # entries: "<base>|<N>"

# ---- 1. divide each master --------------------------------------------------
for master in "$@"; do
    master_abs="$(readlink -f "$master" 2>/dev/null)"
    if [[ -z "$master_abs" || ! -f "$master_abs" ]]; then
        echo "[!] skip $master (not found)" >&2; continue
    fi

    base="$(basename "$master_abs" .json)"; base="${base#config_}"
    divided_dir="$SAT_DIR/divided/$base"

    rm -rf "$divided_dir"
    mkdir -p "$divided_dir"

    echo "[divide] $master -> divided/$base/"
    ( cd "$ROOT_DIR" && "$VENV_PYTHON" "$DIVIDE_PY" --file "$master_abs" --out "$divided_dir" ) \
        > "$divided_dir/divide.log" 2>&1
    rc=$?
    if [[ $rc -ne 0 ]]; then
        echo "[X] divide.py failed for $master_abs (rc=$rc)"
        tail -3 "$divided_dir/divide.log" >&2
        continue
    fi
    N=$(ls "$divided_dir"/conf*.json 2>/dev/null | wc -l)
    if [[ $N -eq 0 ]]; then
        echo "[X] no conf*.json in $divided_dir"; continue
    fi
    echo "         $N sub-configs"
    array_specs+=("$base|$N")
done

[[ ${#array_specs[@]} -eq 0 ]] && { echo "Nothing to submit."; exit 1; }

total=0
for s in "${array_specs[@]}"; do total=$((total + ${s##*|})); done

echo
echo "Submitting ${#array_specs[@]} job arrays, $total total array tasks (%$CONC concurrent per array)"
echo "  cpus=$CPUS  time=$TIME  partition=${PARTITION:-<default>}  mem=${MEM:-<default>}"

if [[ $DRY_RUN -eq 0 && $YES -ne 1 ]]; then
    read -r -p "Submit? [y/N] " ans
    case "${ans,,}" in
        y|yes) ;;
        *) echo "aborted (sub-configs still on disk under SAT/divided/)"; exit 0 ;;
    esac
fi

# ---- 2. submit one sbatch --array per master -------------------------------
submitted=0; failed=0
for spec in "${array_specs[@]}"; do
    base="${spec%%|*}"; N="${spec##*|}"
    last=$((N - 1))
    jobname="sat_${base}"
    out_log="$SAT_DIR/logs/slurm_${jobname}_%A_%a.out"
    err_log="$SAT_DIR/logs/slurm_${jobname}_%A_%a.err"

    envprefix=""
    if [[ "$base" == *dpll4* ]]; then
        envprefix="SAT_PORTFOLIO4=1 "
        echo "[env] $base -> SAT_PORTFOLIO4=1 (4-solver paradigm-robust portfolio)"
    fi

    # \$SLURM_ARRAY_TASK_ID survives into the sbatch-launched bash
    wrap_cmd="cd $SAT_DIR && ${envprefix}$VENV_PYTHON exp.py --file $SAT_DIR/divided/$base/conf\$SLURM_ARRAY_TASK_ID.json"

    sbatch_args=(
        --job-name="$jobname"
        --array="0-${last}%${CONC}"
        --cpus-per-task="$CPUS"
        --threads-per-core=1
        --time="$TIME"
        --output="$out_log"
        --error="$err_log"
        --no-requeue
    )
    [[ -n "$PARTITION" ]] && sbatch_args+=(--partition="$PARTITION")
    [[ -n "$MEM"       ]] && sbatch_args+=(--mem="$MEM")
    sbatch_args+=(--wrap="$wrap_cmd")

    if [[ $DRY_RUN -eq 1 ]]; then
        printf "[dry] sbatch --array=0-%d%%%s --job-name=%s ... %s\n" \
            "$last" "$CONC" "$jobname" "$wrap_cmd"
        submitted=$((submitted + 1))
    else
        if jobid=$(sbatch --parsable "${sbatch_args[@]}" 2>&1); then
            echo "[ok] $jobname  jobid=$jobid  array=0-${last}%${CONC}"
            submitted=$((submitted + 1))
        else
            echo "[X] sbatch failed for $jobname: $jobid"
            failed=$((failed + 1))
        fi
    fi
done

echo
echo "Submitted $submitted/${#array_specs[@]} arrays ($failed failed). Total tasks: $total"
echo "Track:  squeue -u \$USER"
