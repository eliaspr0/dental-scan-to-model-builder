import numpy as np
from dentalbase import dbase

def test_min_area_fan_triangulates_sliver_loop():
    t = np.linspace(0, 2*np.pi, 19, endpoint=False)
    P = np.c_[0.14*np.cos(t), 0.1*np.sin(t), 0.01*np.sin(3*t)]
    T = dbase._min_area_fan(P, set(), np.arange(19))
    assert T is not None and len(T) == 17
    assert set(np.unique(T)) == set(range(19))
