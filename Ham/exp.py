import sys, os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from ng_class import My_Test
import argparse
from template.exp_temp import EXP
from template.gen_plot import SAVE
from template.Transform import Transform
import json
import time

parser = argparse.ArgumentParser()
parser.add_argument("--file", default=None, type=str, help="Config file.")


def gen(dct):
    print("Generating data")

    test = My_Test(
        dct["N"],
        encoding=dct.get("encoding", "trivial"),
        undirected=dct.get("undirected", True),
        solver=dct.get("solver", "multi"),
        max_time=dct.get("max_time", 30.0),
        n_offsets=dct.get("n_offsets", 3),
        solver_seed=dct.get("solver_seed", 0),
        seed_per_call=dct.get("seed_per_call", False),
        seed_n_reps=dct.get("seed_n_reps", 1),
    )
    exper = EXP(test, dct)
    code = exper.run()
    
    print("Data is generated")
    print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    return code
    
def transform(dct, code):
    print("Transforming data")
    
    trns = Transform(code)
    trns.sort()
    
    for f in dct["Functions"]:
        trns.applyFunction(
            dct["Functions"][f]["FunctionName"], 
            dct["Functions"][f]["length"], 
            dct["Functions"][f]["key"], f, 
            dct["Functions"][f]["exact"]
            )
    
    print("Data is transformed")
    print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")
    
def plot(dct, code):
    print("Ploting data")
    
    plt = SAVE()
    for wnd in dct["window"]:
        plt.configure(
            alpha = dct["alpha"],
            conf_int = dct["conf_int"],
            best_plot = dct["best_plot"],
            all_runs_plot = dct["all_runs_plot"],
            plot_save = dct["plot_save"],
            plot_name = dct["plot_name"],
            opts_to_plot = dct["opts_to_plot"],
            errorbar_type = dct["errorbar_type"],
            window = wnd
        )
        if "datas" not in dct:
            dct["datas"]=["id"]
        for data in dct["datas"]:
            # print(data)
            plt.generate_plots(code, data)
    
    print("Data is ploted")
    print("~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~")



if __name__ == '__main__':
    args = parser.parse_args([] if "__file__" not in globals() else None)
    if args.file is not None:
        with open(args.file, 'r') as file:
            s = file.read()
        
        dct = json.loads(s)
        
        for key in dct:
            code_ = None
            if "gen" in dct[key] and ("comment" not in dct[key]["gen"] or dct[key]["gen"]["comment"] == False):
                code_ = gen(dct[key]["gen"])
            
            if "transform" in dct[key] and ("comment" not in dct[key]["transform"] or dct[key]["transform"]["comment"] == False):
                code = code_
                if "code" in dct[key]["transform"]:
                    code = dct[key]["transform"]["code"]
                
                transform(dct[key]["transform"], code)
            
            
            if "plot" in dct[key] and ("comment" not in dct[key]["plot"] or dct[key]["plot"]["comment"] == False):
                code = code_
                if "code" in dct[key]["plot"]:
                    code = dct[key]["plot"]["code"]
                
                plot(dct[key]["plot"], code)
            
    else:
        print("Add flag file to specify config file")
        