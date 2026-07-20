from template.Experiment_config import Experiment_config
from solution_concorde import solve as _solve_concorde
import nevergrad as ng
import numpy as np

_SOLVERS = {"concorde": _solve_concorde}


class My_Test(Experiment_config):

    VALID_ENCODINGS = ("trivial", "prob", "perm_int", "perm_thr",
                       "planted_free", "planted_sym")
    VALID_SOLVERS = ("concorde",)
    # Fixed seed for the 'prob' encoding's common-random edge thresholds (see
    # __init__ / decode_test). Hard-coded so decode is reproducible on every
    # process and machine; changing it changes the threshold realization.
    PROB_THETA_SEED = 0xC0FFEE

    def __init__(self, N, encoding="trivial", undirected=True,
                 solver="multi", max_time=30.0, n_offsets=3,
                 solver_seed=0, seed_per_call=False, seed_n_reps=1):
        super().__init__()
        if encoding not in self.VALID_ENCODINGS:
            raise ValueError(
                f"Unknown encoding {encoding!r}; expected one of "
                f"{self.VALID_ENCODINGS}"
            )
        if solver not in self.VALID_SOLVERS:
            raise ValueError(
                f"Unknown solver {solver!r}; expected one of "
                f"{self.VALID_SOLVERS}"
            )
        self.N = N
        self.encoding = encoding
        self.undirected = bool(undirected)
        self.solver = solver
        self.max_time = float(max_time)
        self.n_offsets = int(n_offsets)
        self.solver_seed = int(solver_seed)
        self.seed_per_call = bool(seed_per_call)
        self.seed_n_reps = max(1, int(seed_n_reps))
        self._call_idx = 0
        self._pairs_undir = self._compute_pairs(N, True)
        self._pairs_dir = self._compute_pairs(N, False)
        self.M = (N * (N - 1) // 2) if self.undirected else N * (N - 1)
        self._pairs = (self._pairs_undir if self.undirected
                       else self._pairs_dir)
        if self.encoding == "prob":
            self._theta_undir = np.random.default_rng(
                self.PROB_THETA_SEED).random(N * (N - 1) // 2)
            self._theta_dir = np.random.default_rng(
                self.PROB_THETA_SEED + 1).random(N * (N - 1))

    @staticmethod
    def _compute_pairs(N, undirected):
        if undirected:
            pairs = np.empty((N * (N - 1) // 2, 2), dtype=np.int32)
            e = 0
            for i in range(N):
                for j in range(i + 1, N):
                    pairs[e, 0] = i
                    pairs[e, 1] = j
                    e += 1
        else:
            pairs = np.empty((N * (N - 1), 2), dtype=np.int32)
            e = 0
            for i in range(N):
                for j in range(N):
                    if i != j:
                        pairs[e, 0] = i
                        pairs[e, 1] = j
                        e += 1
        return pairs

    def encode(self):
        if self.encoding == "trivial":
            return ng.p.Array(shape=(self.M,),
                              lower=0, upper=1).set_integer_casting()
        if self.encoding == "prob":
            return ng.p.Array(shape=(self.M,), lower=0.0, upper=1.0)
        if self.encoding == "perm_int":
            return ng.p.Tuple(
                ng.p.Array(shape=(self.M,)),
                ng.p.Scalar(lower=0, upper=self.M).set_integer_casting(),
            )
        if self.encoding == "perm_thr":
            return ng.p.Array(shape=(self.M + 1,), lower=0.0, upper=1.0)
        if self.encoding == "planted_free":
            M = self.N * (self.N - 1) // 2
            return ng.p.Tuple(
                ng.p.Array(shape=(self.N,)),
                ng.p.Array(shape=(M,)),
                ng.p.Scalar(lower=0, upper=self.N).set_integer_casting(),
            )
        if self.encoding == "planted_sym":
            return ng.p.Array(
                shape=(self.n_offsets,), lower=0, upper=self.N // 2
            ).set_integer_casting()
        raise ValueError(f"Unknown encoding: {self.encoding!r}")

    def _genome_M(self, encoded):
        if self.encoding in ("trivial", "prob"):
            return len(np.asarray(encoded))
        if self.encoding == "perm_int":
            scores, _ = encoded
            return len(np.asarray(scores))
        if self.encoding == "perm_thr":
            return len(np.asarray(encoded)) - 1
        raise ValueError(f"Unknown encoding: {self.encoding!r}")

    def decode_test(self, encoded):
        self._call_idx = 0
        if self.encoding == "planted_free":
            return self._decode_planted_free(encoded)
        if self.encoding == "planted_sym":
            return self._decode_planted_sym(encoded)
        actual_M = self._genome_M(encoded)
        M_undir = self.N * (self.N - 1) // 2
        M_dir = self.N * (self.N - 1)
        if actual_M == M_undir:
            is_undir = True
            pairs = self._pairs_undir
        elif actual_M == M_dir:
            is_undir = False
            pairs = self._pairs_dir
        else:
            raise ValueError(
                f"genome size {actual_M} matches neither {M_undir} "
                f"(undirected) nor {M_dir} (directed) for N={self.N}"
            )

        if self.encoding == "trivial":
            mask = np.asarray(encoded, dtype=np.int32).astype(bool)
        elif self.encoding == "prob":
            P = np.asarray(encoded, dtype=np.float64)
            theta = self._theta_undir if is_undir else self._theta_dir
            mask = P > theta
        elif self.encoding == "perm_int":
            scores, k = encoded
            scores = np.asarray(scores)
            k = max(0, min(int(k), actual_M))
            order = np.argsort(scores)
            mask = np.zeros(actual_M, dtype=bool)
            mask[order[:k]] = True
        elif self.encoding == "perm_thr":
            arr = np.asarray(encoded, dtype=np.float64)
            scores, t = arr[:-1], float(arr[-1])
            mask = scores < t
        else:
            raise ValueError(f"Unknown encoding: {self.encoding!r}")

        adj = np.zeros((self.N, self.N), dtype=np.int32)
        rows = pairs[mask, 0]
        cols = pairs[mask, 1]
        adj[rows, cols] = 1
        if is_undir:
            adj[cols, rows] = 1
        return adj

    def _decode_planted_free(self, encoded):
        v_scores, c_scores, k = encoded
        v_scores = np.asarray(v_scores, dtype=np.float64)
        c_scores = np.asarray(c_scores, dtype=np.float64)
        N = self.N
        pairs = self._pairs_undir
        M = pairs.shape[0]

        adj = np.zeros((N, N), dtype=np.int32)
        perm = np.argsort(v_scores)
        cycle = set()
        for i in range(N):
            u = int(perm[i])
            v = int(perm[(i + 1) % N])
            adj[u, v] = adj[v, u] = 1
            cycle.add((u, v) if u < v else (v, u))

        k = max(0, min(int(k), M - N))
        added = 0
        for e in np.argsort(c_scores)[::-1]:
            if added >= k:
                break
            u = int(pairs[e, 0])
            v = int(pairs[e, 1])
            if (u, v) in cycle or adj[u, v]:
                continue
            adj[u, v] = adj[v, u] = 1
            added += 1
        return adj

    def _decode_planted_sym(self, encoded):
        offsets = np.asarray(encoded).ravel()
        N = self.N
        adj = np.zeros((N, N), dtype=np.int32)
        for i in range(N):
            j = (i + 1) % N
            adj[i, j] = adj[j, i] = 1
        for d in offsets:
            d = int(d)
            if d < 2 or d > N // 2:
                continue
            for i in range(N):
                j = (i + d) % N
                if i != j:
                    adj[i, j] = adj[j, i] = 1
        return adj

    def solve_test(self, test):
        if self.seed_per_call:
            self._call_idx += 1
            seed = ((self._call_idx - 1) // self.seed_n_reps) + 1
        else:
            seed = self.solver_seed
        return _solve_concorde(test, self.N, seed=seed)

    def recomendation(self):
        return None
