from abc import ABC, abstractmethod
import nevergrad as ng

class Experiment_config(ABC):
    
    @abstractmethod
    def encode(self): 
        pass

    @abstractmethod
    def decode_test(self, encoded):
        pass

    @abstractmethod
    def solve_test(self, test):
        pass
    
    @abstractmethod
    def recomendation(self):
        return None

    def get_additional_config(self):
        return {}