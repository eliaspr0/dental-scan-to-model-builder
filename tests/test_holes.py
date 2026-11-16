import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dentalbase.dbase import fill_small_holes, boundary_loops


def grid_with_hole(n=12, hole=(5, 6)):
    xs, ys = np.meshgrid(np.arange(n, dtype=float), np.arange(n, dtype=float))
    V = np.c_[xs.ravel(), ys.ravel(), 0.1 * np.sin(xs.ravel())]
    F = []
    for i in range(n - 1):
        for j in range(n - 1):
            a, b, c, d = i * n + j, i * n + j + 1, (i + 1) * n + j, (i + 1) * n + j + 1
            if hole[0] <= i <= hole[1] and hole[0] <= j <= hole[1]:
                continue
            F += [[a, b, d], [a, d, c]]
    return V, np.array(F)


def test_interior_hole_is_closed_without_moving_vertices():
    V, F = grid_with_hole()
    assert len(boundary_loops(F)) == 2
    F2, info = fill_small_holes(V, F)
    assert info['filled'] == 1 and len(boundary_loops(F2)) == 1
    assert F2.max() < len(V)                       # no new vertices
    he = np.vstack([F2[:, [0, 1]], F2[:, [1, 2]], F2[:, [2, 0]]])
    assert len(np.unique(he, axis=0)) == len(he)  # consistent orientation: no directed edge used twice


def test_single_loop_unchanged():
    V, F = grid_with_hole(hole=(99, 99))
    F2, info = fill_small_holes(V, F)
    assert info['filled'] == 0 and np.array_equal(F, F2)


def test_backend_prints_greek_on_legacy_codepage():
    import subprocess
    code = "import sys; sys.path.insert(0, %r); import make_base; make_base._utf8_streams(); print('ζήσης')" % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    r = subprocess.run([sys.executable, '-c', code], capture_output=True, env={**os.environ, 'PYTHONIOENCODING': 'cp1252'})
    assert r.returncode == 0 and 'ζήσης' in r.stdout.decode('utf-8')
