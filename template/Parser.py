import yaml

class Parser:
    def __init__(self):
        self.parsers = {
            "raw_10_cols": self._parse_raw_matrix
        }
    
    def read_file(self, path):
        try:
            with open(path) as f:
                data = list(yaml.safe_load_all(f))
        except:
            raise Exception("No such file")
        
        for test in data:
            for key, val in test.items():
                if isinstance(val, dict) and ("path" in val) and ("format" in val):
                    test[key] = self.parsers[val["format"]](val["path"])
        return data
    
    def _parse_raw_matrix(self, path):
        data = []
        try:
            with open(path) as f:
                for line in f:
                    data.append([int(x) for x in line.rstrip().split()])
        except:
            raise Exception("No such file")
        return data