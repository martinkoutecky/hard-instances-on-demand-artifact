from template.Experiment_config import Experiment_config
import nevergrad as ng
import numpy as np

class My_Test(Experiment_config):

    def __init__(self, N, M, U, solver="cpsat", solver_seed=0,
                 seed_per_call=False, seed_n_reps=1):
        super().__init__()
        self.N = N  # number of jobs
        self.M = M  # number of machines
        self.U = U  # max processing time
        if solver == "cpopt":
            from solution_cpopt import solve
        else:
            from solution import solve
        self._solve = solve
        self.solver_seed = int(solver_seed)
        self.seed_per_call = bool(seed_per_call)
        self.seed_n_reps = max(1, int(seed_n_reps))
        self._call_idx = 0

    def encode(self):
        param = ng.p.Array(shape=(self.N * self.M,), lower=1, upper=self.U)
        param.set_integer_casting()
        return param

    def decode_test(self, encoded):
        self._call_idx = 0
        P = np.asarray(encoded, dtype=np.int64).reshape(self.N, self.M)
        return P

    def solve_test(self, test):
        if self.seed_per_call:
            self._call_idx += 1
            seed = ((self._call_idx - 1) // self.seed_n_reps) + 1
        else:
            seed = self.solver_seed
        return self._solve(test, self.N, self.M, seed=seed)

    def recomendation(self):
        return None
