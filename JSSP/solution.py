"""
Non-permutation flow-shop solver via OR-Tools CP-SAT.

Fixed machine order [0, 1, ..., m-1] for all jobs.
Objective: minimize makespan.

Timer follows the pattern from SATX/solution.py.
"""
import time
import resource
from ortools.sat.python import cp_model

# Timer options (set via set_timer() or config "timer" field):
#
# "process_time" (default)
#   time.process_time() -- CPU time of current process only.
#   Nanosecond resolution. Best for in-process solvers (CP-SAT).
#
# "resource"
#   resource.getrusage() -- CPU time including child processes.
#   ~10ms resolution (kernel tick-based).

_timer = "process_time"


def set_timer(timer_name):
    global _timer
    _timer = timer_name


def _cpu_time():
    if _timer == "resource":
        u_self = resource.getrusage(resource.RUSAGE_SELF)
        u_child = resource.getrusage(resource.RUSAGE_CHILDREN)
        return (u_self.ru_utime + u_self.ru_stime +
                u_child.ru_utime + u_child.ru_stime)
    return time.process_time()


def solve(P, n_jobs, n_machines, seed=0, time_limit=None):
    """Solve F_m || C_max with CP-SAT.

    Each job visits machines in order 0, 1, ..., m-1. Each machine has an
    independent no-overlap constraint; there is no common job permutation.

    Args:
        P: n_jobs x n_machines numpy array of processing times (int, >= 1)
        n_jobs: number of jobs
        n_machines: number of machines
        seed: CP-SAT random_seed. Default 0 = the gt1 tournament setting.
            Deterministic per seed (num_workers=1), but the seed changes the
            search path and can swing proof time ~11x on hard instances.
        time_limit: optional cap in seconds (max_time_in_seconds). None
            (default) = uncapped, the tournament setting; REQUIRED for
            sizes >= 8x4 where proofs can run for minutes.

    Returns:
        float: CPU time in seconds
    """
    model = cp_model.CpModel()

    horizon = int(P.sum())

    starts = {}
    ends = {}
    intervals = {}

    for i in range(n_jobs):
        for j in range(n_machines):
            dur = int(P[i][j])
            s = model.new_int_var(0, horizon, f's_{i}_{j}')
            e = model.new_int_var(0, horizon, f'e_{i}_{j}')
            iv = model.new_interval_var(s, dur, e, f'iv_{i}_{j}')
            starts[i, j] = s
            ends[i, j] = e
            intervals[i, j] = iv

    # Precedence: within each job, operations go in machine order 0..m-1
    for i in range(n_jobs):
        for j in range(n_machines - 1):
            model.add(ends[i, j] <= starts[i, j + 1])

    # No overlap on each machine
    for j in range(n_machines):
        model.add_no_overlap([intervals[i, j] for i in range(n_jobs)])

    # Minimize makespan
    makespan = model.new_int_var(0, horizon, 'makespan')
    model.add_max_equality(makespan, [ends[i, n_machines - 1] for i in range(n_jobs)])
    model.minimize(makespan)

    solver = cp_model.CpSolver()
    solver.parameters.num_workers = 1
    solver.parameters.random_seed = int(seed)
    if time_limit is not None:
        solver.parameters.max_time_in_seconds = float(time_limit)

    t0 = _cpu_time()
    solver.solve(model)
    return _cpu_time() - t0
