from template.Experiment_config import Experiment_config
from solution_concorde import solve as _solve_concorde
import nevergrad as ng
import numpy as np

_SOLVERS = {"concorde": _solve_concorde}


class My_Test(Experiment_config):

    VALID_SOLVERS = ("concorde",)

    def __init__(self, N, L, U, solver="concorde", solver_seed=0,
                 seed_per_call=False, seed_n_reps=1):
        super().__init__()
        if solver not in self.VALID_SOLVERS:
            raise ValueError(
                f"Unknown solver {solver!r}; expected one of "
                f"{self.VALID_SOLVERS}"
            )
        self.N = N
        self.L = L
        self.U = U
        self.solver = solver
        self.solver_seed = int(solver_seed)
        self.seed_per_call = bool(seed_per_call)
        self.seed_n_reps = max(1, int(seed_n_reps))
        self._call_idx = 0

    def encode(self):
        dim = self.N * (self.N - 1) // 2
        param = ng.p.Array(shape=(dim,), lower=self.L, upper=self.U)
        return param

    def decode_test(self, encoded):
        self._call_idx = 0
        N = self.N
        dist = np.zeros((N, N))
        idx = 0
        for i in range(N):
            for j in range(i + 1, N):
                dist[i][j] = dist[j][i] = encoded[idx]
                idx += 1
        return dist

    def solve_test(self, test):
        if self.seed_per_call:
            self._call_idx += 1
            seed = ((self._call_idx - 1) // self.seed_n_reps) + 1
        else:
            seed = self.solver_seed
        return _SOLVERS[self.solver](test, self.N, seed=seed)

    def recomendation(self):
        return None
