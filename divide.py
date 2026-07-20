import json
import argparse
from template.exp_temp import EXP
import copy

parser = argparse.ArgumentParser()
parser.add_argument("--file", default=None, type=str, help="Config file.")
parser.add_argument("--out", default=None, type=str, help="Path to output files.")

if __name__ == '__main__':
    args = parser.parse_args([] if "__file__" not in globals() else None)
    out = ""
    if args.out is not None:
        out = args.out
    if args.file is not None:
        with open(args.file, 'r') as file:
            s = file.read()

        dct = json.loads(s)

        gen_dicts = []
        trans_plot_dict = {}

        for key in dct:
            code_ = None
            gen_dict = None
            if "gen" in dct[key] and ("comment" not in dct[key]["gen"] or dct[key]["gen"]["comment"] == False):
                if "code" in dct[key]["gen"]:
                    code_ = dct[key]["gen"]["code"]
                gen_dict = dct[key]["gen"]

            if "transform" in dct[key] and ("comment" not in dct[key]["transform"] or dct[key]["transform"]["comment"] == False):
                trans_plot_dict["transform"] = dct[key]["transform"]

            if "plot" in dct[key] and ("comment" not in dct[key]["plot"] or dct[key]["plot"]["comment"] == False):
                trans_plot_dict["plot"] = dct[key]["plot"]

            trans_plot_dict = {"task[1]": trans_plot_dict}

            test = None
            exper = EXP(test, gen_dict)
            exper.create_dirs()
            exper.log_file_conf()
            gen_dict = exper.give_conf()

            for opt in gen_dict["opt"]:
                for run in range(gen_dict["opt"][opt]["iters"]):
                    gen_dict_1 = copy.deepcopy(gen_dict)
                    gen_dict_1["opt"] = {opt: gen_dict_1["opt"][opt]}
                    gen_dict_1["opt"][opt]["iters"] = 1
                    gen_dict_1["opt"][opt]["seed"] += run
                    gen_dict_1["opt"][opt]["iter_id"] = run
                    gen_dict_1["worker_mode"] = True
                    gen_dicts.append({"task[1]": {"gen": gen_dict_1}})

            id = 0
            for dct in gen_dicts:
                with open(f"{out}/conf{id}.json", 'w') as f:
                    f.write(json.dumps(dct, indent=4))
                id += 1
            with open(f"{out}/trans_plot.json", 'w') as f:
                f.write(json.dumps(trans_plot_dict, indent=4))

            print(id)

    else:
        print("Add flag file to specify config file")
