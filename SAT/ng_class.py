from template.Experiment_config import Experiment_config
import os
from solution_portfolio import solve as _solve_portfolio
import nevergrad as ng
import numpy as np


class My_Test(Experiment_config):

    VALID_ENCODINGS = ("kcnf", "mprefix")

    def __init__(self, N, Var, encoding="kcnf", l=3):
        super().__init__()
        if encoding not in self.VALID_ENCODINGS:
            raise ValueError(f"Unknown encoding {encoding!r}; expected one "
                             f"of {self.VALID_ENCODINGS}")
        self.N = int(N)
        self.Var = int(Var)
        self.encoding = encoding
        self.l = int(l)

    def encode(self):
        if self.encoding == "kcnf":
            p = ng.p.Array(shape=(self.N * self.l,))
            p.set_integer_casting()
            p.set_bounds(lower=-self.Var, upper=self.Var - 1,
                         method="clipping")
            return p
        dim = 1 + self.N * self.l
        p = ng.p.Array(shape=(dim,))
        init = np.zeros(dim)
        init[0] = self.N // 2  
        p.value = init   
        p.set_integer_casting()
        lower = np.full(dim, -self.Var, dtype=float)
        upper = np.full(dim, self.Var - 1, dtype=float)
        lower[0] = 1
        upper[0] = self.N
        p.set_bounds(lower=lower, upper=upper, method="clipping")
        return p

    def _chunk_to_clause(self, chunk):
        cl_p = [-int(x) for x in chunk if int(x) < 0]
        cl_n = [int(x) + 1 for x in chunk if int(x) >= 0]
        return {"positive": cl_p, "negative": cl_n}

    def decode_test(self, encoded):
        arr = np.asarray(encoded)
        if self.encoding == "kcnf":
            lits = arr
            m = self.N
        else:  # mprefix
            m = max(1, min(self.N, int(arr[0])))
            lits = arr[1:]
        test = []
        for i in range(0, m * self.l, self.l):
            chunk = lits[i:i + self.l]
            if len(chunk) < self.l:
                break
            test.append(self._chunk_to_clause(chunk))
        return test

    def solve_test(self, test):
        return _solve_portfolio(test)

    def recomendation(self):
        return None
