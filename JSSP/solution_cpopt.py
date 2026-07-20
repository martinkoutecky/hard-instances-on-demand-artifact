"""Non-permutation flow shop F_m || C_max via IBM CP Optimizer.

Every job visits the machines in their common order.  The no-overlap
constraint is independent on each machine, so this is not permutation flow
shop despite the repository's historical ``JSSP`` directory name.
"""

import os
import resource
import shutil

from docplex.cp.model import CpoModel
import docplex.cp.config as cpconfig

# Auto-detect cpoptimizer binary
_CPOPT_SEARCH_PATHS = [
    "<home>/cos2220/cpoptimizer/bin/x86-64_linux/cpoptimizer",
    "/work/tsitseip/cos2220/cpoptimizer/bin/x86-64_linux/cpoptimizer",
]

def _find_cpoptimizer():
    env = os.environ.get("CPOPT_EXECFILE")
    if env and os.path.isfile(env) and os.access(env, os.X_OK):
        return env
    found = shutil.which("cpoptimizer")
    if found:
        return found
    for p in _CPOPT_SEARCH_PATHS:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return None

_cpopt_exe = _find_cpoptimizer()
if _cpopt_exe:
    cpconfig.context.solver.local.execfile = _cpopt_exe

cpconfig.context.solver.local.process_start_timeout = 60


def _children_cpu():
    u = resource.getrusage(resource.RUSAGE_CHILDREN)
    return u.ru_utime + u.ru_stime


def solve(P, n_jobs, n_machines, seed=0, time_limit=None):
    mdl = CpoModel()

    ops = {}
    for i in range(n_jobs):
        for j in range(n_machines):
            dur = int(P[i][j])
            ops[i, j] = mdl.interval_var(size=dur, name=f'O_{i}_{j}')

    for i in range(n_jobs):
        for j in range(n_machines - 1):
            mdl.add(mdl.end_before_start(ops[i, j], ops[i, j + 1]))

    for j in range(n_machines):
        mdl.add(mdl.no_overlap([ops[i, j] for i in range(n_jobs)]))

    mdl.minimize(mdl.max(mdl.end_of(ops[i, n_machines - 1])
                         for i in range(n_jobs)))

    kw = {} if time_limit is None else {"TimeLimit": float(time_limit)}
    t0 = _children_cpu()
    result = mdl.solve(Workers=1, RandomSeed=int(seed), LogVerbosity='Quiet',
                       **kw)
    t1 = _children_cpu()

    return t1 - t0
