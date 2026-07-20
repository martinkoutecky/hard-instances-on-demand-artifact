import os

os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["BLIS_NUM_THREADS"] = "1"

import nevergrad as ng
from template.Functions import Functions_arr, Functions_elem
import warnings
import concurrent.futures
import time, traceback

import tqdm


def _diag(where: str):
    try:
        root = os.environ.get("PROJECT_ROOT", os.getcwd())
        with open(os.path.join(root, "dmtcp_worker_diag.log"), "a") as f:
            f.write(f"\n===== ng_testing {where} pid={os.getpid()} t={time.time():.3f} =====\n")
            traceback.print_exc(file=f)
            f.flush()
    except Exception:
        pass

def _evaluate_candidate(tests_obj, encoded, trials_per_eval, agg_func_name, unflat_func_name):
    """
    Standalone evaluation function for ProcessPoolExecutor/ThreadPoolExecutor.
    Receives only picklable data. Returns (raw_time, loss_value).
    """
    test_instance = tests_obj.decode_test(encoded)
    execution_times = []
    for _ in range(trials_per_eval):
        execution_times.append(tests_obj.solve_test(test_instance))
        
    agg_function = getattr(Functions_arr, agg_func_name)
    raw_time = agg_function(execution_times)
    
    transformation_func = getattr(Functions_elem, unflat_func_name)
    loss_value = transformation_func(raw_time)
    
    return raw_time, loss_value


class NG_Testing():
    """
    Handles the execution of Nevergrad optimization stress tests.
    """

    def __init__(self):
        
        # State tracking
        self.index = 0
        
        # Core Configuration
        self.id = None
        self.name = ""
        self.budget = 10000
        self.opt = "Shiwa"
        self.trials_per_eval = 1
        self.seed = None

        self.save_test = False
        self.save_result = False
        self.log_dir = None

        # Function mappings
        self.agg_func_name = "median"
        self.unflat_func_name = "negative"
        
        # Execution environment
        self.num_worker = 1
        self.batch = False
        self.batch_size = 1
        self.debug = 0
        self.position = -1

        # External dependencies
        self.tests = None
        self.queue = None
        self.status = None
        self.pbar = None
        self.optimizer = None
        self.executor = None

    def clear(self):
        """Resets the internal state for a new test run."""
        return

    def configure(self, **kwargs):
        """
        Dynamically updates class attributes based on provided kwargs.
        Raises a warning if an unknown parameter is passed.
        """
        for key, value in kwargs.items():
            name = f"{key}"
            if hasattr(self, name):
                setattr(self, name, value)
            else:
                warnings.warn(f"Attempted to configure unknown attribute: {key}")

    def upd(self, optimizer: ng.optimizers.base.Optimizer, candidate: ng.p.Parameter, loss_value: float):
        """Callback triggered by Nevergrad after each evaluation."""
        pass

    def _process_result(self, candidate, raw_time, loss_value):
        idx = self.index
        self.index += 1

        if self.queue:
            self.queue.put({
                "signal": 0, 
                "id": self.id, 
                "name": self.name, 
                "value": raw_time,
                "iter": idx, 
                "test": candidate.args[0], 
                "loss": loss_value, 
                "batch": self.batch_size
            })
        
        if self.pbar:
            self.pbar.update(self.batch_size)
            
        self.optimizer.tell(candidate, loss_value)

    def _ask_tell_loop(self):
        """Manual ask/tell loop replacing optimizer.minimize().

        ask() and tell() stay single-threaded (no nevergrad race condition).
        Evaluations run in parallel via self.executor.
        Supports both batch and steady-state evaluations depending on self.batch.
        """
        if self.batch:
            # Batch mode: wait for all to finish before next ask
            batch_size = max(1, self.num_worker)
            while self.optimizer.num_tell < self.budget:
                n = min(batch_size, self.budget - self.optimizer.num_tell)

                candidates = [self.optimizer.ask() for _ in range(n)]
                if not candidates:
                    break

                if self.executor is not None:
                    futures = [
                        self.executor.submit(
                            _evaluate_candidate,
                            self.tests, c.args[0],
                            self.trials_per_eval,
                            self.agg_func_name,
                            self.unflat_func_name
                        )
                        for c in candidates
                    ]
                    results = [f.result() for f in futures]
                else:
                    results = [
                        _evaluate_candidate(
                            self.tests, c.args[0],
                            self.trials_per_eval,
                            self.agg_func_name,
                            self.unflat_func_name
                        )
                        for c in candidates
                    ]

                for candidate, (raw_time, loss_value) in zip(candidates, results):
                    self._process_result(candidate, raw_time, loss_value)

        else:
            # Steady-state mode: tell as soon as an evaluation completes
            # This implements a sliding window of 'num_worker' concurrent evaluations.
            futures = {}  # future -> candidate
            
            while self.optimizer.num_tell < self.budget:
                # 1. Fill the buffer up to num_worker or remaining budget
                while len(futures) < self.num_worker and self.optimizer.num_ask < self.budget:
                    candidate = self.optimizer.ask()
                    
                    if self.executor is not None:
                        future = self.executor.submit(
                            _evaluate_candidate,
                            self.tests, candidate.args[0],
                            self.trials_per_eval,
                            self.agg_func_name,
                            self.unflat_func_name
                        )
                        futures[future] = candidate
                    else:
                        # Sequential fallback
                        raw_time, loss_value = _evaluate_candidate(
                            self.tests, candidate.args[0],
                            self.trials_per_eval,
                            self.agg_func_name,
                            self.unflat_func_name
                        )
                        self._process_result(candidate, raw_time, loss_value)
                        # In sequential mode, we don't use the futures dict, 
                        # so we break the inner loop to re-check budget.
                        break

                if not futures:
                    # If we aren't using an executor (sequential), the inner loop 
                    # already handled the evaluation. Re-check the outer loop.
                    if self.executor is None:
                        continue
                    # If we have an executor but no futures, we've submitted everything.
                    if self.optimizer.num_ask >= self.budget and not futures:
                        break

                # 2. Wait for at least one evaluation to complete
                if futures:
                    done, _ = concurrent.futures.wait(
                        futures.keys(),
                        return_when=concurrent.futures.FIRST_COMPLETED
                    )

                    # 3. Process completed evaluations and remove from buffer
                    for f in done:
                        candidate = futures.pop(f)
                        try:
                            raw_time, loss_value = f.result()
                            self._process_result(candidate, raw_time, loss_value)
                        except Exception as e:
                            print(f"Evaluation failed in worker: {e}")
                            _diag(f"f.result/_process_result num_tell={getattr(self.optimizer,'num_tell','?')} num_ask={getattr(self.optimizer,'num_ask','?')}")
                            # We still need to tell the optimizer something or at least count it
                            # so we don't hang, but usually this is a fatal error.
                            raise

    def stress(self):
        """
        Main entry point for starting the optimization stress test.
        """
        self.clear()
        self.pbar = tqdm.tqdm(
            total=self.budget, 
            desc=f"Run {self.name} (ID {self.id}) with {self.opt}", 
            unit="evals", 
            position = self.position
            )
        
        self.send_conf()
        param = self.tests.encode()
        if self.seed is not None:
            param.random_state.seed(self.seed)
        
        recomendation = self.tests.recomendation()
    
        with warnings.catch_warnings():
            if self.debug < 2:
                warnings.filterwarnings("ignore")
            
            try:
                self.optimizer = ng.optimizers.registry[self.opt](
                    parametrization = param,
                    budget = self.budget,
                    num_workers = self.num_worker
                )
            except KeyError as e:
                raise ValueError(f"Invalid Nevergrad optimizer specified: {self.opt}") from e
            
            self.index = 0
            
            self.optimizer.register_callback("tell", self.upd)
            if recomendation is not None:
                for test in recomendation:
                    self.optimizer.suggest(test)
                    
            self._ask_tell_loop()

    def send_conf(self):
        """Pushes the initial configuration state to the message queue."""
        if not self.queue:
            raise Exception(f"No queue was given")
            
        
        self.queue.put({
                "signal": 1,
                "budget": self.budget,
                "optimizer": self.opt,
                "runs_of_iter": self.trials_per_eval,
                "run_id": self.id,
                "function": self.agg_func_name,
                "function_unflat": self.unflat_func_name,
                "debug": self.debug,
                "name": self.name,
                "seed": self.seed
            })
