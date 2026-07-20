"""SAT hardness = MIN over a FOUR-solver, PARADIGM-DIVERSE portfolio.

Experimental variant of solution_portfolio.py (the authors' ffa-long run). Differences
from the canonical 3-branch portfolio:

  * baseline minisat22  ->  REPLACED by **kissat** (binary, strongest CDCL).
  * NEW 4th branch: **march_cu -p** -- a complete look-ahead/DPLL solver
    (different paradigm from CDCL). Putting it in the `min` makes the hardness
    PARADIGM-ROBUST: an instance only counts as hard if it survives CDCL *and*
    look-ahead. (CDCL-only champions become easy here -- that is the point.)

    hardness = min( kissat(F),
                    8ms + breakid->cadical195(F),    # symmetry guard (PHP)
                    cryptominisat(F),                # XOR guard (parity)
                    march_cu -p (F) )                # look-ahead/DPLL guard

Selected only when env SAT_PORTFOLIO4=1 (ng_class.py / exp.py switch); the
canonical 3-solver portfolio is otherwise untouched.

Same min mechanics as the canonical module: branches run as parallel children,
first valid finisher (= wall-fastest = the min) wins, the rest are killed, so an
instance easy for ANY technique costs ~wall(min). BreakID is charged a flat 8ms
(argmax-invariant; never rewards symmetry). Per-branch cap = _BRANCH_TIMEOUT_S.

Unlike the first dpll4 deployment, BreakID preprocessing runs INSIDE its
branch's worker (async), not in the parent: degenerate mid-search genomes
(duplicate clauses -> huge symmetry groups) make BreakID slow, and paying that
synchronously billed every eval's wall (~2.5 s/eval on chimera) while the
recorded value stayed 8 ms flat. Symmetric-hard instances still record as easy
(the other branches are slow there, so BreakID->CDCL wins the race anyway);
easy instances no longer wait. All branch temp files live in a per-solve temp
dir removed by the parent -- workers killed mid-race die by SIGKILL (finally
blocks never run), so they must not own their temp files.

Binary branches (kissat, march): the DIMACS is written to a temp file, the
solver runs as a subprocess timed by getrusage(RUSAGE_CHILDREN) CPU seconds
(comparable to the in-process branches' process_time). Orphan-proofed with
PR_SET_PDEATHSIG so a binary dies the instant its worker is killed (no leaked
solver eating a core when a faster branch wins).
"""
import os
import sys
import time
import select
import signal
import ctypes
import resource
import tempfile
import subprocess
import multiprocessing as mp

from pysat.solvers import Solver

_HERE = os.path.dirname(os.path.abspath(__file__))
# Self-contained artifact layout: all four solvers' binaries live in ./bin/
# (in the working repo this module sat in SAT/ and read SAT_BENCHMARK/tools/).
_TOOLS = os.path.join(_HERE, "bin")
_BREAKID = os.path.join(_HERE, "bin", "breakid")
_KISSAT = os.path.join(_TOOLS, "kissat")
_MARCH = os.path.join(_TOOLS, "march_cu")
_env = os.environ.copy()
_env["LD_LIBRARY_PATH"] = os.path.join(_HERE, "bin") + ":" + _env.get("LD_LIBRARY_PATH", "")

_BREAKID_FLAT_S = 0.008    # flat BreakID charge (see canonical module docstring)
_BRANCH_TIMEOUT_S = 120.0  # per-branch / hardness cap (the authors: 120 s)
_timer = "process_time"

_libc = ctypes.CDLL("libc.so.6", use_errno=True)
_PR_SET_PDEATHSIG = 1


def _pdeathsig():
    """preexec_fn: kill this child the moment its parent (the worker) dies."""
    _libc.prctl(_PR_SET_PDEATHSIG, signal.SIGKILL)


def set_timer(timer_name):
    global _timer
    _timer = timer_name


# ── DIMACS ────────────────────────────────────────────────────────────────────

def _to_clauses(test):
    """test = [{positive:[v...], negative:[v...]}, ...] -> DIMACS int clauses."""
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


def _write_dimacs(cnf_list, n_vars, tmpdir=None):
    fd, path = tempfile.mkstemp(suffix=".cnf", dir=tmpdir)
    with os.fdopen(fd, "w") as f:
        f.write(f"p cnf {n_vars} {len(cnf_list)}\n")
        for cl in cnf_list:
            f.write(" ".join(map(str, cl)) + " 0\n")
    return path


def _run_binary(which, cnf_list, n_vars, cap, tmpdir=None):
    """Run kissat / march on the CNF; return CPU seconds (getrusage), or `cap`
    on timeout. Orphan-proofed via PR_SET_PDEATHSIG."""
    path = _write_dimacs(cnf_list, n_vars, tmpdir)
    try:
        if which == "march":
            cmd = [_MARCH, path, "-p"]      # file FIRST, then plain-DPLL mode
        else:                              # kissat: no model witness
            cmd = [_KISSAT, "-n", path]
        r0 = resource.getrusage(resource.RUSAGE_CHILDREN)
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL,
                           preexec_fn=_pdeathsig, timeout=cap)
        except subprocess.TimeoutExpired:
            return cap
        r1 = resource.getrusage(resource.RUSAGE_CHILDREN)
        dt = (r1.ru_utime - r0.ru_utime) + (r1.ru_stime - r0.ru_stime)
        return max(dt, 0.0)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _breakid_preprocess(cnf_list, n_vars, tmpdir=None):
    """Run BreakID; return symmetry-broken clauses (original on any failure).

    Runs inside the symmetry branch's worker: PDEATHSIG so the binary dies with
    the worker when a faster branch wins the race (no orphan eating a core)."""
    fd, in_path = tempfile.mkstemp(suffix=".cnf", dir=tmpdir)
    out_path = in_path + ".bk.cnf"
    try:
        with os.fdopen(fd, "w") as f:
            f.write(f"p cnf {n_vars} {len(cnf_list)}\n")
            for cl in cnf_list:
                f.write(" ".join(map(str, cl)) + " 0\n")
        r = subprocess.run([_BREAKID, "--verb", "0", in_path, out_path],
                           env=_env, capture_output=True, timeout=60,
                           preexec_fn=_pdeathsig)
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


# ── Guard detection (once, at import) ─────────────────────────────────────────

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


def _detect_binary(which):
    """Trivial SAT (clause [1]) must return SAT (exit 10)."""
    path = _BINPATH[which]
    if not os.path.exists(path):
        return False, f"{which} binary missing at {path}"
    cnf = _write_dimacs([[1]], 1)
    try:
        cmd = [path, cnf, "-p"] if which == "march" else [path, "-n", cnf]
        r = subprocess.run(cmd, capture_output=True, timeout=20)
        if r.returncode in (10, 20):       # SAT / UNSAT
            return True, f"exit {r.returncode}"
        err = (r.stderr or b"").decode(errors="replace").strip().splitlines()
        return False, err[-1] if err else f"returncode {r.returncode}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
    finally:
        try:
            os.unlink(cnf)
        except OSError:
            pass


_BINPATH = {"kissat": _KISSAT, "march": _MARCH}
_STRONG_CDCL, _STRONG_ERR = _detect_strong_cdcl()
_CMS_BACKEND, _CMS_ERR = _detect_cms()
_HAVE_BREAKID, _BREAKID_ERR = _detect_breakid()
_HAVE_KISSAT, _KISSAT_ERR = _detect_binary("kissat")
_HAVE_MARCH, _MARCH_ERR = _detect_binary("march")


def active_guards():
    return {
        "baseline CDCL (kissat)": {"active": _HAVE_KISSAT,
                                   "detail": _KISSAT_ERR or "kissat"},
        "symmetry (BreakID->CDCL)": {
            "active": _HAVE_BREAKID and _STRONG_CDCL is not None,
            "detail": (_STRONG_CDCL if (_HAVE_BREAKID and _STRONG_CDCL)
                       else (_BREAKID_ERR or _STRONG_ERR)),
        },
        "XOR (CryptoMiniSat)": {"active": _CMS_BACKEND is not None,
                                "detail": _CMS_BACKEND or _CMS_ERR},
        "look-ahead/DPLL (march_cu)": {"active": _HAVE_MARCH,
                                       "detail": _MARCH_ERR or "march_cu -p"},
    }


def require_full_portfolio():
    g = active_guards()
    missing = [k for k, v in g.items() if not v["active"]]
    if missing:
        lines = [f"  - {k}: {g[k]['detail']}" for k in missing]
        raise RuntimeError(
            "SAT 4-portfolio is missing required guard(s); the paradigm-robust "
            "hardness objective would be void:\n" + "\n".join(lines))


def print_guards(stream=sys.stderr):
    print("[SAT 4-portfolio] active guards:", file=stream)
    for k, v in active_guards().items():
        mark = "OK " if v["active"] else "!! "
        print(f"  {mark}{k}: {v['detail']}", file=stream)
    stream.flush()


# ── Solve path ────────────────────────────────────────────────────────────────

def _solve_worker(kind, name, clauses, n_vars, conn, tmpdir=None):
    """Child process: solve, send back this branch's CPU seconds."""
    try:
        # Own process group, so the parent can killpg() the branch AND any
        # binary it spawned. PDEATHSIG alone races: a worker killed between
        # its subprocess's fork and the child's prctl() leaves an orphan
        # (observed ~1/20 on degenerate evals); group-kill has no window.
        os.setpgrp()
        if kind == "binary":
            dt = _run_binary(name, clauses, n_vars, _BRANCH_TIMEOUT_S, tmpdir)
        elif kind == "breakid+pysat":
            # symmetry branch: BreakID runs HERE (async), not in the parent;
            # dt stays cadical-only -- BreakID itself is charged the flat 8ms.
            pp = _breakid_preprocess(clauses, n_vars, tmpdir)
            s = Solver(name=name, bootstrap_with=pp)
            t0 = time.process_time()
            s.solve()
            dt = time.process_time() - t0
            s.delete()
        elif kind == "pycryptosat":
            import pycryptosat
            s = pycryptosat.Solver(threads=1)
            for cl in clauses:
                s.add_clause(cl)
            t0 = time.process_time()
            s.solve()
            dt = time.process_time() - t0
        else:  # pysat backend by name
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
    """(kind, name, clauses, offset) for every live branch."""
    specs = []
    if _HAVE_KISSAT:                                          # baseline CDCL
        specs.append(("binary", "kissat", cnf_list, 0.0))
    if _STRONG_CDCL is not None:                              # symmetry branch
        if _HAVE_BREAKID:
            # BreakID runs inside the worker (async); flat 8ms charge unchanged
            specs.append(("breakid+pysat", _STRONG_CDCL, cnf_list,
                          _BREAKID_FLAT_S))
        else:
            specs.append(("pysat", _STRONG_CDCL, cnf_list, 0.0))
    if _CMS_BACKEND == "pycryptosat":                        # XOR branch
        specs.append(("pycryptosat", None, cnf_list, 0.0))
    elif _CMS_BACKEND == "pysat:cms":
        specs.append(("pysat", "cms", cnf_list, 0.0))
    if _HAVE_MARCH:                                          # look-ahead/DPLL
        specs.append(("binary", "march", cnf_list, 0.0))
    return specs


def solve(test):
    """Portfolio hardness (CPU seconds) = min over the 4 branches."""
    cnf_list, n_vars = _to_clauses(test)
    if not cnf_list:
        return 0.0

    specs = _branch_specs(cnf_list, n_vars)

    # Parent owns ALL branch temp files: losers are SIGKILLed mid-race, so
    # their finally-unlinks never run -- without this, /tmp leaks per eval.
    tmp = tempfile.TemporaryDirectory(prefix="satp4_")
    workers = []
    for kind, name, clauses, off in specs:
        parent_conn, child_conn = mp.Pipe(duplex=False)
        p = mp.Process(target=_solve_worker,
                       args=(kind, name, clauses, n_vars, child_conn, tmp.name))
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
                try:                       # kill the worker's whole group
                    os.killpg(p.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    p.kill()               # worker died / not yet setpgrp'd
            p.join(timeout=5)
            pc.close()
        tmp.cleanup()

    return best if best is not None else _BRANCH_TIMEOUT_S
