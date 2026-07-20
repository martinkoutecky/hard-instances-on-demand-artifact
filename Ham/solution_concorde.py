import os
import resource
import shutil
import tempfile
import time
import uuid

import numpy as np

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


def solve(adj, N, seed=0):
    from concorde._concorde import _CCutil_gettsplib, _CCtsp_solve_dat

    sym = np.maximum(adj, np.asarray(adj).T).astype(np.int32)
    weights = np.where(sym > 0, 0, 1).astype(int)

    old_cwd = os.getcwd()
    scratch_dir = tempfile.mkdtemp(prefix="ham_concorde_")
    try:
        tsp_fd, tsp_path = tempfile.mkstemp(suffix=".tsp", dir=scratch_dir)
        with os.fdopen(tsp_fd, "w") as f:
            f.write(f"NAME: ham\nTYPE: TSP\nDIMENSION: {N}\n")
            f.write("EDGE_WEIGHT_TYPE: EXPLICIT\n"
                    "EDGE_WEIGHT_FORMAT: UPPER_ROW\n")
            f.write("EDGE_WEIGHT_SECTION\n")
            for i in range(N):
                row = " ".join(str(int(weights[i][j]))
                               for j in range(i + 1, N))
                f.write(row + "\n")
            f.write("EOF\n")

        devnull = os.open(os.devnull, os.O_WRONLY)
        old_stdout, old_stderr = os.dup(1), os.dup(2)
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        try:
            os.chdir(scratch_dir)
            ncount, data = _CCutil_gettsplib(tsp_path)
            name = uuid.uuid4().hex[:9]
            t0 = _cpu_time()
            _CCtsp_solve_dat(ncount, data, name, -1, True, seed)
            elapsed = _cpu_time() - t0
        finally:
            os.chdir(old_cwd)
            os.dup2(old_stdout, 1)
            os.dup2(old_stderr, 2)
            os.close(old_stdout)
            os.close(old_stderr)
            os.close(devnull)
    finally:
        shutil.rmtree(scratch_dir, ignore_errors=True)

    return elapsed
