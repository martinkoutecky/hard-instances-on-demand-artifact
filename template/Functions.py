from numpy import median
import numpy as np

class Functions_arr():
    def mean(arr):
        return sum(arr) / len(arr)
    
    def sum(arr):
        return sum(arr)
    
    def max(arr):
        return max(arr)
        
    def min(arr):
        return min(arr)
    
    def median(arr):
        return median(arr)

    def geometric_mean(arr):
        a = np.asarray(arr, dtype=float)
        return float(np.exp(np.log(np.clip(a, 1e-12, None)).mean()))

    def geomean3_median(arr):
        a = np.asarray(arr, dtype=float)
        if a.size % 3 != 0:
            raise ValueError(
                f"geomean3_median expects len(arr) divisible by 3, "
                f"got {a.size}"
            )
        groups = a.reshape(-1, 3)
        log_g = np.log(np.clip(groups, 1e-12, None)).mean(axis=1)
        return float(np.median(np.exp(log_g)))

class Functions_elem():
    def identity(elem):
        return elem
    
    def negative(elem):
        return -elem
    
    def Lorentzian(elem):
        return 1 / (1 + elem * elem)
    
    def exp(elem):
        return np.exp(elem)
    
    def gaussian(elem):
        return np.exp(-elem * elem)

    def neg_log(elem):
        # Concave/log-domain pressure: gradient large at small x, small at
        # large x. Pairs with F=geometric_mean (already log-averaged) -- gives
        # nevergrad a fully multiplicative loss. Clip guards x near zero.
        return -np.log(np.maximum(elem, 1e-12))

    def neg_pow2(elem):
        # Convex/accelerating pressure: "push harder once already hard" --
        # opposite of Lorentzian's saturation. Tests if late-stage flattening
        # has been bottlenecking adversarial search.
        return -(elem * elem)

class Functions_trans():
    def max(arr):
        return [np.argmax(arr)]
        
    def min(arr):
        return [np.argmin(arr)]
    
    def median(arr):
        med = sorted(arr)[len(arr)//2]
        for i in range(len(arr)):
            if arr[i] == med:
                return [i]
        return []