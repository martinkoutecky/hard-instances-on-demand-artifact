import os
import json
import pickle
import warnings
from collections import deque
import numpy as np
import zarr
import numcodecs
from tqdm import tqdm

from template.get_files import get_path
from template.Functions import Functions_trans

class Transform():
    """
    Handles post-processing, sorting, and applying transformations 
    to Zarr experiment data.
    """
    def __init__(self, run_code: str):
        self.file_path = get_path(run_code)
        
        if not os.path.exists(self.file_path):
            raise FileNotFoundError(f"Run directory not found: {self.file_path}")

        self.raw_data = self._load_raw_data()
        self.sorted_data = {}
    
    def _load_raw_data(self):
        """Reads conf.json and loads the corresponding Zarr arrays into memory."""
        conf_file = f"{self.file_path}/conf.json"
        
        try:
            with open(conf_file, 'r') as file:
                config = json.load(file).get('opt', {})
        except FileNotFoundError:
            raise FileNotFoundError(f"Missing config file: {conf_file}")
        
        loaded_data = {}
        
        for optimizer, opt_config in config.items():
            for iteration in range(opt_config.get('iters', 0)):
                base_dir = f"{self.file_path}/data/{optimizer}/{iteration}"
                
                if not os.path.exists(base_dir):
                    warnings.warn(f"Skipping missing data directory: {base_dir}")
                    continue
                
                try:
                    loaded_data[(optimizer, iteration)] = {
                        "loss": zarr.open(f"{base_dir}/loss.zarr")[:],
                        "tests": zarr.open(f"{base_dir}/tests.zarr")[:],
                        "values": zarr.open(f"{base_dir}/values.zarr")[:],
                        "ids": zarr.open(f"{base_dir}/ids.zarr")[:],
                        "path": base_dir
                    }
                    print(f"Loaded data for {optimizer} iteration {iteration} from {base_dir} successfully.")
                    print(f"Loss shape: {loaded_data[(optimizer, iteration)]['loss'].shape}, Tests shape: {loaded_data[(optimizer, iteration)]['tests'].shape}, Values shape: {loaded_data[(optimizer, iteration)]['values'].shape}, IDs shape: {loaded_data[(optimizer, iteration)]['ids'].shape}")
                except Exception as e:
                    warnings.warn(f"Failed to load data from {base_dir}. Error: {e}")
                
        return loaded_data

    def sort(self):
        """Sorts the data by iteration IDs and overwrites the Zarr arrays in a new 'id' subfolder."""
        pbar = tqdm(total=len(self.raw_data), desc="Sorting Data")
        for (optimizer, iteration), run_data in self.raw_data.items():
            id_array = run_data["ids"]
            sorted_indices = id_array.argsort()

            filtered_ids = [x for x in sorted_indices if run_data["loss"][x] != None and run_data["values"][x] != None]
    
            loss_sorted = run_data["loss"][filtered_ids]
            values_sorted = run_data["values"][filtered_ids]
            tests_sorted = run_data["tests"][filtered_ids]
            
            output_dir = f"{run_data['path']}/id"
            os.makedirs(output_dir, exist_ok=True)
            
            # Save sorted Loss
            loss_z = zarr.open(
                f"{output_dir}/loss.zarr",
                mode='w',
                shape=(len(loss_sorted),),
                chunks=(1000,),
                dtype=np.float64,
                zarr_version=2
            )
            loss_z[:] = loss_sorted

            # Save sorted Tests
            tests_z = zarr.open(
                f"{output_dir}/tests.zarr",
                mode='w',
                shape=(len(tests_sorted),),
                chunks=(1000,),
                dtype=object,
                object_codec=numcodecs.Pickle(),
                zarr_version=2
            )
            tests_z[:] = tests_sorted

            # Save sorted Values
            values_z = zarr.open(
                f"{output_dir}/values.zarr",
                mode='w',
                shape=(len(values_sorted),),
                chunks=(1000,),
                dtype=np.float64,
                zarr_version=2
            )
            values_z[:] = values_sorted
            
            self.sorted_data[(optimizer, iteration)] = {
                "loss": loss_z,
                "tests": tests_z,
                "values": values_z,
                "path": run_data["path"]
            }
            pbar.update(1)
        pbar.close()

    
    def applyFunction(self, function_name: str, window_size: int, target_array_key: str, output_name: str, exact: bool = False):
        """
        Applies a transformation function over a rolling window and saves the filtered data.
        """
        if not self.sorted_data:
            warnings.warn("sorted_data is empty. Did you forget to call sort()?")
            return

        pbar = tqdm(total=len(self.sorted_data), desc=f"Applying {function_name}")
        for opt_key, run_data in self.sorted_data.items():
            target_array = run_data[target_array_key]
            
            try:
                transform_func = getattr(Functions_trans, function_name)
            except AttributeError:
                raise AttributeError(f"Function '{function_name}' not found in Functions_trans")
            
            rolling_window = deque(maxlen=window_size)
            filtered_ids = []
            
            for idx, element in enumerate(target_array):
                rolling_window.append(element)
                
                if exact and len(rolling_window) != window_size:
                    continue
                
                offset = max(idx - len(rolling_window) + 1, 0)
                window_ids = transform_func(list(rolling_window))
                
                filtered_ids.extend([w_idx + offset for w_idx in window_ids])
                
            filtered_loss = run_data["loss"][filtered_ids]
            filtered_values = run_data["values"][filtered_ids]
            filtered_tests = run_data["tests"][filtered_ids]
            output_path = f"{run_data['path']}/{output_name}"
            
            os.makedirs(output_path, exist_ok=True)
            
            zarr.open(
                os.path.join(output_path, "loss.zarr"),
                mode='w',
                shape=(len(filtered_loss),),
                chunks=(1000,),
                dtype=np.float64,
                zarr_version=2
            )[:] = filtered_loss

            
            zarr.open(
                os.path.join(output_path, "tests.zarr"),
                mode='w',
                shape=(len(filtered_tests),),
                chunks=(1000,),
                dtype=object,
                object_codec=numcodecs.Pickle(),
                zarr_version=2
            )[:] = filtered_tests
            
            
            zarr.open(
                os.path.join(output_path, "values.zarr"),
                mode='w',
                shape=(len(filtered_values),),
                chunks=(1000,),
                dtype=np.float64,
                zarr_version=2
            )[:] = filtered_values
            pbar.update(1)
        pbar.close()
    
    def rerunTests(self, only_failed: bool = False, output_name: str = "rerun", ng_class=None):
        for (optimizer, iteration), run_data in self.raw_data.items():
            id_array = run_data["ids"]
            sorted_indices = id_array.argsort()

            filtered_ids = []
            
            if only_failed:
                filtered_ids = [x for x in sorted_indices if run_data["tests"][x] != None and run_data["values"][x] == None]
            else:
                filtered_ids = sorted_indices
            
            rerunned_values = run_data["values"]
            rerunned_losses = run_data["loss"]
            rerunned_tests  = run_data["tests"]
            
            
            for idx in filtered_ids:
                test_instance = rerunned_tests[idx]
                decoded_test = ng_class.tests.decode_test(test_instance)
                raw_time = ng_class.solve_test(decoded_test)
                rerunned_values[idx] = raw_time
                rerunned_losses[idx] = 0
                
            rerunned_values = rerunned_values[sorted_indices]
            rerunned_losses = rerunned_losses[sorted_indices]
            rerunned_tests  = rerunned_tests[sorted_indices]
            
            output_path = f"{run_data['path']}/{output_name}"
            os.makedirs(output_path, exist_ok=True)
            
            
            zarr.open(
                os.path.join(output_path, "loss.zarr"),
                mode='w',
                shape=(len(rerunned_losses),),
                chunks=(1000,),
                dtype=np.float64,
                zarr_version=2
            )[:] = rerunned_losses

            with open(os.path.join(output_path, "tests.pkl"), 'wb') as f:
                pickle.dump(list(rerunned_tests), f)
                
            zarr.open(
                os.path.join(output_path, "tests.zarr"),
                mode='w',
                shape=(len(rerunned_tests),),
                chunks=(1000,),
                dtype=object,
                object_codec=numcodecs.Pickle(),
                zarr_version=2
            )[:] = rerunned_tests

            zarr.open(
                os.path.join(output_path, "values.zarr"),
                mode='w',
                shape=(len(rerunned_values),),
                chunks=(1000,),
                dtype=np.float64,
                zarr_version=2
            )[:] = rerunned_values