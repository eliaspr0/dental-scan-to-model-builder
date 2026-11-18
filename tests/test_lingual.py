import numpy as np
from dentalbase import dbase

def test_arch_side_outside_positive_inside_negative():
    t = np.linspace(0.2, np.pi - 0.2, 4000)
    row = np.c_[30 * np.cos(t), 30 * np.sin(t), np.zeros_like(t)]          # tooth row on a 30 mm arc
    out = np.c_[40 * np.cos(t), 40 * np.sin(t), np.zeros_like(t)]
    inn = np.c_[20 * np.cos(t), 20 * np.sin(t), np.zeros_like(t)]
    V = np.vstack([row, out, inn]); mask = np.zeros(len(V), bool); mask[:4000] = True
    s = dbase.arch_side(V, mask)
    assert (s[4000:8000] > 0.9).all() and (s[8000:] < -0.9).all()
