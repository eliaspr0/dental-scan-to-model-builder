"""Tooth seeds must not be pulled onto ragged-border / spike curvature outliers."""
import numpy as np
from dentalbase import pipeline as PL


def _grid(n=110, s=0.3):
    xs, ys = np.meshgrid(np.arange(n) * s, np.arange(n) * s)
    V = np.c_[xs.ravel(), ys.ravel(), np.zeros(n * n)]
    idx = np.arange(n * n).reshape(n, n)
    a, b, c, d = idx[:-1, :-1].ravel(), idx[:-1, 1:].ravel(), idx[1:, 1:].ravel(), idx[1:, :-1].ravel()
    return V, np.r_[np.c_[a, b, c], np.c_[a, c, d]]


def test_spikes_do_not_steal_the_seeds():
    V, F = _grid()
    n = int(np.sqrt(len(V)))
    X, Y = V[:, 0], V[:, 1]
    V[:, 2] = 1.0                                   # flat gingiva
    teeth = np.zeros(len(V), bool)
    for cx in (9, 16, 23):                          # three "teeth": raised, mildly convex
        t = (X - cx) ** 2 + (Y - 16) ** 2 < 2.5 ** 2
        teeth |= t
    V[teeth, 2] = 4.0
    H = np.zeros(len(V))
    H[teeth] = 1.5
    H += np.random.RandomState(0).normal(0, 0.05, len(V))
    border = (X < 0.7) | (Y < 0.7) | (X > X.max() - 0.7) | (Y > Y.max() - 0.7)
    V[border, 2] = 6.0                              # ragged, high, hugely curved border junk
    H[border] = 5e5
    p, bv = PL.segment_crowns(V, F, H)
    got = p > 0.5
    assert got[teeth].mean() > 0.6, 'real teeth were not detected'
    assert got[border].mean() < 0.2, 'border junk was taken for teeth'
