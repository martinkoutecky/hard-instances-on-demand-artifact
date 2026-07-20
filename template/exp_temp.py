import os
import hashlib

from collections import defaultdict
import pickle
from tqdm import tqdm
import numpy as np
import time, copy, json, select, traceback
import sys, zarr
import signal
import numcodecs


from concurrent.futures import ProcessPoolExecutor

from multiprocessing import Manager, Pool
import multiprocessing
import multiprocessing.pool
import queue
import psutil

from template.ng_testing import NG_Testing


# Pool workers are daemonic by default, which forbids them from spawning
# child processes. solution_multi.solve() needs to spawn CP-SAT/Concorde
# children -- so the pool workers must be non-daemonic. NoDaemonPool below
# is the standard workaround (subclass Process to ignore daemon=True).
class _NoDaemonProcess(multiprocessing.Process):
    @property
    def daemon(self):
        return False

    @daemon.setter
    def daemon(self, value):
        pass


class _NoDaemonContext(type(multiprocessing.get_context())):
    Process = _NoDaemonProcess


class NoDaemonPool(multiprocessing.pool.Pool):
    def __init__(self, *args, **kwargs):
        kwargs['context'] = _NoDaemonContext()
        super().__init__(*args, **kwargs)

def limit_process_cores(num_cores: int) -> list:
    """Restrict *this process* and all its children (including Pool workers) to `num_cores`."""
    p = psutil.Process(os.getpid())
    # Start from the affinity we already have, not range(cpu_count()):
    # under a SLURM cgroup on a shared node the process may only own an
    # arbitrary subset of host CPUs, and asking for others raises EINVAL.
    all_cores = p.cpu_affinity()
    allowed = all_cores[:num_cores]
    p.cpu_affinity(allowed)
    print(f"[✓] Limited CPU affinity to cores: {allowed}")
    return allowed



class WorkerSignal:
    DATA = 0
    CONFIG = 1
    DONE = -1
    ERROR = -2
    INTERRUPT = -3

class EXP():
    """
    Manages the execution of multiple Nevergrad optimization experiments
    across a pool of parallel workers.
    """
    def __init__(self, test, config: dict):
        self.test = test
        self.config = config

        self.pbar = None
        self.vl_opt = None

        # Generate a unique hash for this run's log directory
        self.current_time_str = time.ctime()
        self.code = hashlib.sha1(self.current_time_str.encode()).hexdigest()[:4]
        self.log_dir = f"logs/log_{self.current_time_str}_{self.code}"
        
        self.debug = 0

        self.total_steps = 0

        self.datas_zarr = {}
        self.loss_zarr = {}
        self.tests_zarr = {}
        self.ids_zarr = {}
        
        self.data = defaultdict(dict)
        
        self._apply_default_config()
        
    def _apply_default_config(self):
        """Fills in missing configuration values with sensible defaults."""
        if "debug" not in self.config:
            self.config["debug"] = 0
        
        self.debug = self.config["debug"]
        
        
        if "code" not in self.config:
            self.config["code"] = self.code
        else:
            self.code = self.config["code"]
            self.log_dir = f"logs/log_{self.code}"
        
        
        # Propagate global iters to individual optimizers
        if "iters" in self.config:
            iters = self.config["iters"]
            for optim in self.config["opt"]:
                if "iters" not in self.config["opt"][optim]:
                    self.config["opt"][optim]["iters"] = iters
        
        # Propagate global budget
        if "budget" in self.config:
            budget = self.config["budget"]
            for optim in self.config["opt"]:
                if "budget" not in self.config["opt"][optim]:
                    self.config["opt"][optim]["budget"] = budget

        unflat_func = self.config.get("F_unflat", "negative")
        for optim in self.config["opt"]:
            if "F_unflat" not in self.config["opt"][optim]:
                self.config["opt"][optim]["F_unflat"] = unflat_func

        # Base of the optimizer-seed sequence. A top-level config "seed"
        # makes the whole run reproducible: each (opt, iter) still gets a
        # distinct seed = base + cumulative iters (then +run in get_args),
        # and a per-opt "seed" below still overrides. Defaults to 1 (legacy).
        seed_counter = self.config.get("seed", 1)
        if "salt" not in self.config:
            self.config["salt"] = 0
        salt = self.config["salt"]
        for optim in self.config["opt"]:
            if "seed" not in self.config["opt"][optim]:
                self.config["opt"][optim]["seed"] = seed_counter + salt
            seed_counter += self.config["opt"][optim]["iters"]

        for optim in self.config["opt"]:
            if "iter_id" not in self.config["opt"][optim]:
                self.config["opt"][optim]["iter_id"] = 0

        print("Default configuration values configured")

    def create_dirs(self):
        """Sets up the directory structure and initializes Zarr arrays on disk."""
        try:
            chunk = int(self.config.get("chunk", 1000))

            os.makedirs("logs", exist_ok=True)
            os.makedirs(self.log_dir, exist_ok=True)
            os.makedirs(f"{self.log_dir}/data", exist_ok=True)

            for optim in self.config["opt"]:
                os.makedirs(f"{self.log_dir}/data/{optim}", exist_ok=True)
                iter_id = self.config["opt"][optim].get("iter_id", 0)
                iters = self.config["opt"][optim]["iters"]
                for run in range(iter_id, iter_id + iters):
                    run_path = f"{self.log_dir}/data/{optim}/{run}"
                    os.makedirs(run_path, exist_ok=True)

                    self.datas_zarr[(optim, run)] = zarr.open(
                        f"{run_path}/values.zarr",
                        mode='a',
                        shape=(0,),
                        chunks=(chunk,),
                        dtype=np.float64,
                        zarr_version=2
                        )

                    self.loss_zarr[(optim, run)] = zarr.open(
                        f"{run_path}/loss.zarr",
                        mode='a',
                        shape=(0,),
                        chunks=(chunk,),
                        dtype=np.float64,
                        zarr_version=2
                        )

                    self.ids_zarr[(optim, run)] = zarr.open(
                        f"{run_path}/ids.zarr",
                        mode='a',
                        shape=(0,),
                        chunks=(chunk,),
                        dtype=np.int32,
                        zarr_version=2
                        )


                    self.tests_zarr[(optim, run)] = zarr.open(
                        f"{run_path}/tests.zarr",
                        mode='a',
                        shape=(0,),
                        chunks=(chunk,),
                        dtype=object,
                        object_codec=numcodecs.Pickle(),
                        zarr_version=2
                        )

        except Exception as e:
            print(f"WARNING: Couldn't complete create_dirs: {e}")
            # traceback.print_exc()

    def log_file_conf(self):
        """Saves the main experiment configuration to a JSON file."""
        if self.config.get("worker_mode", False):
            return
        try:
            with open(f"{self.log_dir}/conf.json", 'w') as f:
                f.write(json.dumps(self.config, indent = 4))
        except Exception as e:
            print(f"WARNING: Couldn't save log_file_conf: {e}")
            # traceback.print_exc()
        
    def give_conf(self):
        """Returns the experiment configuration dictionary."""
        return self.config

    def save_data(self):
        """Flushes in-memory lists to the Zarr arrays on disk and clears memory."""
        try:
            for optim in self.config["opt"]:
                iter_id = self.config["opt"][optim].get("iter_id", 0)
                iters = self.config["opt"][optim]["iters"]
                for run in range(iter_id, iter_id + iters):
                    key = (optim, run)
                    
                    datas = []
                    loss = []
                    tests = []
                    ids = []
                    
                    for iter_id, (value, loss_val, test) in self.data[key].items():
                        datas.append(value)
                        loss.append(loss_val)
                        tests.append(test)
                        ids.append(iter_id)


                    if len(tests) > 0:
                        arr_to_app = np.empty(len(tests), dtype = object)
                        for i, val in enumerate(tests):
                            arr_to_app[i] = val
                        self.tests_zarr[key].append(arr_to_app)

                    
                    if len(loss) > 0:
                        self.loss_zarr[key].append(np.array(loss, dtype=np.float64))
                    
                    if len(datas) > 0:
                        self.datas_zarr[key].append(np.array(datas, dtype=np.float64))
                    
                    if len(ids) > 0:
                        self.ids_zarr[key].append(np.array(ids, dtype=np.int32))
                    
                    # print(self.tests[key])
                    
                    self.data[key] = {}
        except Exception as e:
            print(f"WARNING: Couldn't save save_data: {e}")
            # traceback.print_exc()

    def save_optimizers_status(self, results_dict: dict):
        """Writes out the final termination status of all runs."""
        try:
            with open(f"{self.log_dir}/optimizers_status", "a") as f:
                for opt in self.config["opt"]:
                    iter_id = self.config["opt"][opt].get("iter_id", 0)
                    iters = self.config["opt"][opt]["iters"]
                    for itr in range(iter_id, iter_id + iters):
                        status_code = results_dict.get((opt, itr), 0)
                        if status_code == 0:
                            f.write(f"{opt} in iteration {itr}: Didn't start or end\n")
                        if status_code == 1:
                            f.write(f"{opt} in iteration {itr}: Successful\n")
                        if status_code == 2:
                            f.write(f"{opt} in iteration {itr}: Error\n")
                        if status_code == 3:
                            f.write(f"{opt} in iteration {itr}: Interapted\n")
        except Exception as e:
            print(f"WARNING: Couldn't save save_optimizers_status: {e}")
            # traceback.print_exc()
                        
    def save_opt_conf(self, dct):
        """Saves the full gen-level config into the per-iter directory.

        Writes self.config (encoding, N, salt, optimizer block, ...) so each
        iter dir is self-describing if the top-level conf.json is lost.
        """
        try:
            optim = dct["name"]
            run = dct["run_id"]
            with open(f"{self.log_dir}/data/{optim}/{run}/conf.json", "w") as f:
                f.write(json.dumps(self.config, indent=4))
        except Exception as e:
            print(f"WARNING: Couldn't save save_opt_conf: {e}")
            # traceback.print_exc()

    def save_system_stats(self, allowed_cores):
        """Logs CPU usage and core information to a file."""
        try:
            p = psutil.Process(os.getpid())
            cpu_usage = p.cpu_percent(interval=1.0)
            with open(f"{self.log_dir}/system_stats.log", "a") as f:
                stats = {
                    "time": time.ctime(),
                    "total_cores_on_machine": psutil.cpu_count(),
                    "cores_configured_in_config": self.config.get("worker_cores"),
                    "actual_cores_allowed": allowed_cores,
                    "process_cpu_usage_percent": cpu_usage,
                    "system_cpu_usage_percent": psutil.cpu_percent(percpu=True)
                }
                f.write(json.dumps(stats, indent=4) + "\n")
        except Exception as e:
            print(f"WARNING: Couldn't save system stats: {e}")
        
    def get_args(self, progress_queue, worker_per_task: int) -> list:
        """Constructs the arguments list for the multiprocessing pool."""
        arg_list = []
        task_id_counter = 1
        for optim in self.config["opt"]:
            for run in range(self.config["opt"][optim]["iters"]):
                ng_test = copy.deepcopy(self.test)
                opt_config = self.config["opt"][optim]
                args = (
                    ng_test,
                    opt_config["Solver"],
                    run+opt_config["iter_id"],
                    self.config,
                    progress_queue,
                    self.debug,
                    worker_per_task,
                    opt_config["budget"],
                    optim,
                    opt_config["F_unflat"],
                    task_id_counter,
                    opt_config["seed"]+run
                    )
                arg_list.append(args)
                task_id_counter += 1
        return arg_list

    def check_for_save(self) -> bool:
        """
        Non-blocking check to see if the user pressed 's' in the terminal.
        Relies on termios/tty being set to cbreak mode.
        """
        if select.select([sys.stdin], [], [], 0) == ([sys.stdin], [], []):
            key = sys.stdin.read(1)
            return key.lower() == 's'
        return False

    @staticmethod
    def _worker_init():
        """Initializer to make worker processes ignore SIGINT."""
        signal.signal(signal.SIGINT, signal.SIG_IGN)

    def run(self) -> str:
        """Main execution loop setting up workers, progress tracking, and result aggregation."""
        self.create_dirs()
        self.log_file_conf()
        
        results_dict = {(opt, itr): 0 for opt in self.config["opt"] for itr in range(self.config["opt"][opt]["iters"])}
        
        self.futures = []
        
        max_val = np.float64(0.0)
        min_loss_val = np.float64(2.0)
        
        manager = Manager()
        progress_queue = manager.Queue()
        
        tasks_done = 0
        self.total_tasks = sum(self.config["opt"][solver]["iters"] for solver in self.config["opt"])
        self.total_steps = sum(self.config["opt"][solver]["iters"] * self.config["opt"][solver]["budget"] for solver in self.config["opt"])
        
        worker_cores = self.config.get("worker_cores", psutil.cpu_count())
        allowed_cores = limit_process_cores(worker_cores)
        self.save_system_stats(allowed_cores)
        
        worker_per_task = max(1, (self.config["worker"]-1) // self.total_tasks)
        
        all_args = self.get_args(progress_queue, worker_per_task)

        pbar = tqdm(total = self.total_steps, desc="Overall Progress", position = 0)
        
        actual_workers = min(self.config["worker"], worker_cores)
        
        pool = NoDaemonPool(processes = actual_workers, maxtasksperchild=worker_per_task, initializer=EXP._worker_init)

        # with Pool(self.config["worker"], maxtasksperchild=worker_per_task) as pool:
        try:

            for args in all_args:
                pool.apply_async(EXP.worker_proc, args)
            pool.close()

            last_vals = []
            # Periodic flush so preemption / walltime kills don't lose
            # in-RAM progress (the only other save_data() call sits past
            # the loop and never runs if we get SIGTERMed mid-run).
            last_periodic_save = time.time()

            while tasks_done < self.total_tasks:
                if self.check_for_save():
                    pbar.write(f"\n[!] Save triggered. Writing .npy...")
                    self.save_data()
                    pbar.write("[√] Save complete.")

                if time.time() - last_periodic_save > 60:
                    self.save_data()
                    last_periodic_save = time.time()

                try:
                    msg = progress_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                
                signal_type = msg["signal"]

                if signal_type == WorkerSignal.CONFIG:
                    self.save_opt_conf(msg)
                    continue

                elif signal_type == WorkerSignal.DATA:
                    key = (msg["name"], msg["id"])
                    
                    if "value" in msg:
                        self.data[key][msg["iter"]] = (msg["value"], msg["loss"], msg["test"])
                    else:
                        self.data[key][msg["iter"]] = (None, None, msg["test"])
                        continue
                        
                    
                    pbar.update(msg["batch"])
                    
                    last_vals.append(msg["value"])
                    
                    max_val = max(msg["value"], max_val)
                    
                    min_loss_val = min(min_loss_val, msg["loss"])
                    
                    while len(last_vals)>100:
                        last_vals.pop(0)
                    
                    pbar.set_postfix({
                            "Tasks": f" {tasks_done}/{self.total_tasks}",
                            "Mean(100)": f" {np.mean(last_vals):.6f}",
                            "Min loss": f" {min_loss_val:.6f}",
                            "Max(100)": f" {np.max(last_vals):.6f}",
                            "Max": f" {max_val:.6f}"
                    })
                
                elif signal_type in (WorkerSignal.DONE, WorkerSignal.ERROR, WorkerSignal.INTERRUPT):
                    tasks_done += 1
                    results_dict[msg["name"], msg["id"]] = abs(signal_type)
                
                pbar.update(0)
                pbar.refresh()
            
    
            for optim in self.config["opt"]:
                for run in range(self.config["opt"][optim]["iters"]):
                    print()
            
            last_tm = time.time()-60
            while any([bool(self.data[key]) for key in self.data]):
                tm = time.time()
                if tm - last_tm > 60:  # If more than 60 seconds have passed
                    pbar.write(f"\n[!] Save triggered. Writing .npy...")
                    self.save_data()
                    pbar.write("[√] Save complete.")
                    last_tm = tm

                if self.check_for_save():
                    pbar.write(f"\n[!] Save triggered. Writing .npy...")
                    self.save_data()
                    pbar.write("[√] Save complete.")
                # print([bool(self.data[key]) for key in self.data])
                    
            self.save_optimizers_status(results_dict)
            
            print("\n[✓] All tasks completed. Terminating workers...")
    
            pool.join()
            
        except KeyboardInterrupt:
            print("\n[!] Keyboard interrupt received. Terminating workers...")
            pool.terminate()
            pool.join()
            sys.exit(1)
        finally:
            pbar.close()
            manager.shutdown()
        
        return self.code
    
    @staticmethod
    def worker_proc(user_test, optim, iter_id, config_dict, progress_queue, debug, worker, budget, name, F_unflat, task_position, seed):
        """
        Isolated process that runs the Nevergrad testing instance.
        Must remain a static method so arguments can be pickled.
        """
        if debug < 1:
            try:
                devnull = open(os.devnull, 'w')
                os.dup2(devnull.fileno(), 1)  # stdout
                os.dup2(devnull.fileno(), 2)  # stderr
                devnull.close()
            except Exception:
                print("WARNING: Debug value 2 has not been activated")
                pass

        
        try:
            # Processes, not threads: the Concorde C call holds the GIL (threads
            # would serialise) and solve() times with process-wide process_time().
            with ProcessPoolExecutor(max_workers=worker) as local_executor:
                ng_test = NG_Testing()
                ng_test.configure(
                    budget = budget,
                    opt = optim,
                    trials_per_eval = config_dict["k"],
                    agg_func_name = config_dict["F"],
                    unflat_func_name = F_unflat,
                    num_worker = worker,
                    batch = config_dict["batch"],
                    id = iter_id,
                    tests = user_test,
                    debug = debug,
                    queue = progress_queue,
                    name = name,
                    position = task_position,
                    seed = seed,
                    executor = local_executor
                )
                
                ng_test.stress()
            
            
            # print(f"[✓] Worker {name} iteration {iter_id} completed successfully.")
            
            progress_queue.put({
                "signal": WorkerSignal.DONE,
                "id": iter_id,
                "name": name
                })

        except Exception as e:
            print("WARNING: Exception caught in worker: ", e)
            try:
                root = os.environ.get("PROJECT_ROOT", os.getcwd())
                with open(os.path.join(root, "dmtcp_worker_diag.log"), "a") as fdiag:
                    fdiag.write(f"\n===== worker_proc except Exception pid={os.getpid()} t={time.time():.3f} optim={optim} iter={iter_id} =====\n")
                    traceback.print_exc(file=fdiag)
                    fdiag.flush()
            except Exception:
                pass
            progress_queue.put({
                "signal": WorkerSignal.INTERRUPT,
                "id": iter_id,
                "name": name
                })
        
        except KeyboardInterrupt:
            progress_queue.put({
                "signal": WorkerSignal.ERROR,
                "id": iter_id,
                "name": name
                })
        return
