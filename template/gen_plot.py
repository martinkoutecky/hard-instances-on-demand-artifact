import os
import pickle
from multiprocessing import Process, Queue, cpu_count, Manager, Pool
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm
import json
from template.Functions import Functions_arr
from template.get_files import get_path
import zarr



class SAVE():
    def __init__(self):
        self.best_r = None
        self.alpha = 0.6
        self.conf_int = 95
        self.errorbar_type = "sd"
                
        self.all_values = {}
        
        self.best_plot = None
        
        self.all_runs_plot = None
        
        self.plot_save = None
        
        self.budget = None
        self.plot_name = None
        self.file_path = None
        self.pbar = None
        
        self.opts_to_plot = None
        self.window = 1
        
        self.max_budget = 0
        self.runs = 0
        self.opt_runs = {}
        
    def configure(self, **kwargs):
        for key, value in kwargs.items():
            name = f"{key}"
            if hasattr(self, name):
                setattr(self, name, value)
    
    def clean(self):
        self.all_values = {}
        
        self.budget = None
        
        self.opts_to_plot = None
        
        self.max_budget = 0
        self.runs = 0
        self.opt_runs = {}
    
    def upd(self):
        self.pbar.update(1)
        
    def create_dir(self, data_name):
        os.makedirs(f"{self.file_path}/plots", exist_ok=True)
        os.makedirs(f"{self.file_path}/plots/{data_name}", exist_ok=True)

    def get_data(self, code, data_name, data_key):
        self.file_path = get_path(code)
        
        # print(self.file_path)
        
        self.create_dir(data_name)
        
        self.conf = None
        with open(f"{self.file_path}/conf.json") as f:
            self.conf = json.loads(f.read())["opt"]
        
        
        if self.opts_to_plot == []:
            self.opts_to_plot = list(self.conf.keys())
        
        missing_keys = set(self.opts_to_plot) - self.conf.keys()
        
        if missing_keys:
            raise KeyError(f"The following keys from your list are missing in the dictionary: {missing_keys}")
        
        self.conf = {k:self.conf[k] for k in self.opts_to_plot}
        # print(self.conf)
        
        self.all_r = {}
        
        for optim, val in self.conf.items():
            # print(optim, val)
            for run in range(val["iters"]):
                if run in self.opt_runs:
                    self.opt_runs[run].append(optim)
                else:
                    self.opt_runs[run]=[optim]
                self.all_values[(optim, run)] = zarr.open(self.file_path+"/"+"data"+"/"+optim+"/"+str(run)+"/"+data_name+"/"+"values.zarr", zarr_version=2)[:]

                
                # print(self.all_values)
                
                self.conf[optim]["budget"] = len(self.all_values[(optim, run)])
                self.max_budget = max(self.max_budget, len(self.all_values[(optim, run)]))
                self.runs = max(self.runs, val["iters"])
            
    def generate_plots(self, code, data_name="id", data_key="values"):
        self.clean()
        
        self.get_data(code, data_name, data_key)
        total_it = (self.best_plot * len(self.plot_name) + self.all_runs_plot)
        
        for iter_id in range(self.runs):
            if self.plot_save:
                total_it += len(self.plot_name)
        
        self.pbar = tqdm(total = total_it, desc="Overall Progress", position = 0)
        if self.best_plot:
            # print(self.file_path, f"{self.file_path}/best_plot")
            os.makedirs(f"{self.file_path}/plots/{data_name}/best_plot", exist_ok=True)
            self.best_plot_func(f"{self.file_path}/plots/{data_name}/best_plot")

        if self.all_runs_plot:
            self.plot_conf_save(f"{self.file_path}/plots/{data_name}/all_runs_lineplot")

        for iter_id in range(self.runs):
            
            # data = self.all_values[(optim, iter_id)]
            data = {}
            for optim in self.opt_runs[iter_id]:
                # print(optim)
                data[optim] = self.all_values[(optim, iter_id)]
            
            if self.plot_save:
                self.plot_save_f(f"{self.file_path}/plots/{data_name}", data, iter_id)
        
        self.pbar.close()


    def best_plot_func(self, file):
        self.best_r = {}
        for optim in self.conf.keys():
            if optim not in self.best_r:
                self.best_r[optim] = []
            for iters in range(self.conf[optim]["iters"]):
                for bdg in range(len(self.all_values[(optim,iters)])):
                    while len(self.best_r[optim])<=bdg:
                        self.best_r[optim].append(0)
                    self.best_r[optim][bdg] = max(self.best_r[optim][bdg], self.all_values[(optim,iters)][bdg])

        for plot in self.plot_name:
            os.makedirs(f"{file}/{plot}", exist_ok=True)

            self.plot(self.best_r, plot, f"{file}/{plot}/Solvers: {self.best_r.keys()}.png")
            self.upd()

    def plot_save_f(self, file, data, iter_id):
        for plot_names in self.plot_name:
            os.makedirs(f"{file}/{plot_names}", exist_ok=True)

            self.plot(data, plot_names, f"{file}/{plot_names}/run={iter_id} Solvers: {data.keys()}.png")
            self.upd()

    def plot_conf_save(self, file):
        os.makedirs(f"{file}", exist_ok=True)

        l = self.all_values.keys()
        g = list(set([a for (a, b) in l]))

        self.plot_conf(self.all_values, self.conf_int, self.window, f"{file}/{self.errorbar_type}, Window: {self.window}, Solvers: {g}.png")
        self.upd()

    def plot(self, dct, plot_name, file):
        # df = pd.DataFrame({
        #     'Iteration': np.arange(len(next(iter(dict(dct).values())))),
        #     **dct
        # })
        # df_long = df.melt(id_vars='Iteration', var_name='label', value_name='Time')
        
        df_list = []
        for label, values in dct.items():
            temp_df = pd.DataFrame({
                'Iteration': np.arange(len(values)),
                'Time': values,
                'label': label
            })
            df_list.append(temp_df)
        
        df_long = pd.concat(df_list, ignore_index=True)

        plt.figure(figsize=(10, 6))
        if plot_name == "lineplot" or plot_name == "scatterplot":
            getattr(sns, plot_name)(data=df_long, x='Iteration', y='Time', hue='label', palette='tab10', alpha = self.alpha)
        else:
            getattr(sns, plot_name)(data=df_long, x='Iteration', y='Time', hue='label', palette='tab10')
        plt.title('Time Series Plot')
        plt.legend(loc='upper right')
        plt.savefig(file)
        plt.close()


    def plot_conf(self, dct, conf_int, window, file):
        df_list = []
        for (name, run_id), run_values in dct.items():
            smoothed_values = pd.Series(run_values).rolling(window=window, min_periods=1).mean()
            
            temp_df = pd.DataFrame({
                'Iteration': range(len(run_values)),
                'Time': smoothed_values,
                'Algorithm': name,
                'Run_ID': run_id
            })
            df_list.append(temp_df)

        df_long = pd.concat(df_list, ignore_index=True)

        if self.errorbar_type == "ci":
            eb = ("ci", conf_int)
        else:
            eb = self.errorbar_type

        plt.figure(figsize=(10, 6))
        sns.lineplot(
            data=df_long,
            x='Iteration',
            y='Time',
            hue='Algorithm',
            errorbar=eb,
            estimator="mean",
            alpha = self.alpha
        )
        plt.title("Time Series Plot")
        plt.legend(loc='upper right')
        plt.savefig(file)
        plt.close()