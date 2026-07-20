import os
import sys
import time
import select
import tempfile
import subprocess
import multiprocessing as mp

from pysat.solvers import Solver

_HERE = os.path.dirname(os.path.abspath(__file__))
_BREAKID = os.path.join(_HERE, "breakid")
_env = os.environ.copy()
_env["LD_LIBRARY_PATH"] = _HERE + ":" + _env.get("LD_LIBRARY_PATH", "")

_BREAKID_FLAT_S = 0.008   # flat BreakID charge (see module docstring)
_BRANCH_TIMEOUT_S = 300.0  # hard cap if every branch hangs
_timer = "process_time"


def set_timer(timer_name):
    """API-compat with the other tasks; pysat/pycryptosat backends are timed
    in-process with process_time regardless."""
    global _timer
    _timer = timer_name



def _detect_strong_cdcl():
    last = "no candidate tried"
    for name in ("kissat404", "cadical195", "cadical153", "glucose4"):
        try:
            s = Solver(name=name)
            s.delete()
            return name, None
        except Exception as e:
            last = f"{name}: {type(e).__name__}"
    return None, last


def _detect_cms():
    try:
        import pycryptosat  # noqa: F401
        s = pycryptosat.Solver(threads=1)
        s.add_clause([1])
        s.solve()
        return "pycryptosat", None
    except Exception as e:
        pyc_err = f"pycryptosat: {type(e).__name__}"
    try:
        s = Solver(name="cms", bootstrap_with=[[1]])
        s.solve()
        s.delete()
        return "pysat:cms", None
    except Exception as e:
        return None, f"{pyc_err}; pysat:cms: {type(e).__name__}"


def _detect_breakid():
    if not os.path.exists(_BREAKID):
        return False, "breakid binary missing"
    try:
        r = subprocess.run([_BREAKID, "--version"], env=_env,
                           capture_output=True, timeout=15)
        if r.returncode == 0:
            return True, None
        err = (r.stderr or b"").decode(errors="replace").strip().splitlines()
        return False, err[0] if err else f"returncode {r.returncode}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


_STRONG_CDCL, _STRONG_ERR = _detect_strong_cdcl()
_CMS_BACKEND, _CMS_ERR = _detect_cms()
_HAVE_BREAKID, _BREAKID_ERR = _detect_breakid()


def active_guards():
    return {
        "symmetry (BreakID)": {
            "active": _HAVE_BREAKID, "detail": _BREAKID_ERR,
        },
        "strong CDCL": {
            "active": _STRONG_CDCL is not None,
            "detail": _STRONG_CDCL or _STRONG_ERR,
        },
        "XOR (CryptoMiniSat)": {
            "active": _CMS_BACKEND is not None,
            "detail": _CMS_BACKEND or _CMS_ERR,
        },
        "baseline (minisat22)": {"active": True, "detail": "minisat22"},
    }


def require_full_portfolio():
    g = active_guards()
    missing = [k for k, v in g.items() if not v["active"]]
    if missing:
        lines = [f"  - {k}: {g[k]['detail']}" for k in missing]
        raise RuntimeError(
            "SAT portfolio is missing required guard(s); the PHP/parity "
            "robustness objective would be void:\n" + "\n".join(lines))


def print_guards(stream=sys.stderr):
    print("[SAT portfolio] active guards:", file=stream)
    for k, v in active_guards().items():
        mark = "OK " if v["active"] else "!! "
        print(f"  {mark}{k}: {v['detail']}", file=stream)
    stream.flush()


def _to_clauses(test):
    cnf_list = []
    max_var = 0
    for cl in test:
        clause = []
        for p in cl["positive"]:
            clause.append(int(p))
            if abs(int(p)) > max_var:
                max_var = abs(int(p))
        for n in cl["negative"]:
            clause.append(-int(n))
            if abs(int(n)) > max_var:
                max_var = abs(int(n))
        if clause:
            cnf_list.append(clause)
    return cnf_list, max_var


def _breakid_preprocess(cnf_list, n_vars):
    fd, in_path = tempfile.mkstemp(suffix=".cnf")
    out_path = in_path + ".bk.cnf"
    try:
        with os.fdopen(fd, "w") as f:
            f.write(f"p cnf {n_vars} {len(cnf_list)}\n")
            for cl in cnf_list:
                f.write(" ".join(map(str, cl)) + " 0\n")
        r = subprocess.run([_BREAKID, "--verb", "0", in_path, out_path],
                          env=_env, capture_output=True, timeout=60)
        if r.returncode != 0 or not os.path.exists(out_path):
            return cnf_list
        pp = []
        with open(out_path) as f:
            for line in f:
                line = line.strip()
                if not line or line[0] in "cp":
                    continue
                lits = [int(x) for x in line.split()]
                if lits and lits[-1] == 0:
                    lits = lits[:-1]
                if lits:
                    pp.append(lits)
        return pp or cnf_list
    except Exception:
        return cnf_list
    finally:
        for p in (in_path, out_path):
            try:
                os.unlink(p)
            except OSError:
                pass


def _solve_worker(kind, name, clauses, conn):
    try:
        if kind == "pycryptosat":
            import pycryptosat
            s = pycryptosat.Solver(threads=1)
            for cl in clauses:
                s.add_clause(cl)
            t0 = time.process_time()
            s.solve()
            dt = time.process_time() - t0
        else:
            s = Solver(name=name, bootstrap_with=clauses)
            t0 = time.process_time()
            s.solve()
            dt = time.process_time() - t0
            s.delete()
        conn.send(dt)
    except Exception:
        conn.send(None)
    finally:
        conn.close()


def _branch_specs(cnf_list, n_vars):
    specs = [("pysat", "minisat22", cnf_list, 0.0)] 
    if _STRONG_CDCL is not None: 
        if _HAVE_BREAKID:
            pp = _breakid_preprocess(cnf_list, n_vars)
            specs.append(("pysat", _STRONG_CDCL, pp, _BREAKID_FLAT_S))
        else:
            specs.append(("pysat", _STRONG_CDCL, cnf_list, 0.0))
    if _CMS_BACKEND == "pycryptosat": 
        specs.append(("pycryptosat", None, cnf_list, 0.0))
    elif _CMS_BACKEND == "pysat:cms":
        specs.append(("pysat", "cms", cnf_list, 0.0))
    return specs


def solve(test):
    cnf_list, n_vars = _to_clauses(test)
    if not cnf_list:
        return 0.0

    specs = _branch_specs(cnf_list, n_vars)

    workers = []   # (proc, parent_conn, offset)
    for kind, name, clauses, off in specs:
        parent_conn, child_conn = mp.Pipe(duplex=False)
        p = mp.Process(target=_solve_worker,
                       args=(kind, name, clauses, child_conn))
        p.start()
        child_conn.close()
        workers.append((p, parent_conn, off))

    fd_map = {pc.fileno(): (p, pc, off) for (p, pc, off) in workers}
    best = None
    remaining = dict(fd_map)
    deadline = time.time() + _BRANCH_TIMEOUT_S
    try:
        while remaining and best is None:
            timeout = max(0.0, deadline - time.time())
            readable = select.select(list(remaining), [], [], timeout)[0]
            if not readable:
                break
            for fd in readable:
                p, pc, off = remaining.pop(fd)
                try:
                    dt = pc.recv()
                except EOFError:
                    dt = None
                if dt is not None:
                    best = dt + off
                    break
    finally:
        for p, pc, off in workers:
            if p.is_alive():
                p.kill()
            p.join(timeout=5)
            pc.close()

    return best if best is not None else _BRANCH_TIMEOUT_S
