import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import dentalbase.dbase as D


def cloud(seed=0, n=3000):
    r = np.random.RandomState(seed)
    P = r.randn(n, 3) * np.array([30.0, 20.0, 3.0])          # flat in z: the smallest axis is z
    N = np.tile([0.0, 0.0, 1.0], (n, 1))
    H = r.randn(n)
    return P, N, H


def test_estimate_up_matches_with_and_without_eigh(monkeypatch):
    P, N, H = cloud()
    ref = D.estimate_up(P, N, H)

    def boom(*a, **k):
        raise np.linalg.LinAlgError('Eigenvalues did not converge')
    monkeypatch.setattr(np.linalg, 'eigh', boom)
    alt = D.estimate_up(P, N, H)
    assert abs(float(ref @ alt)) > 0.999999


def test_nan_curvature_and_normals_do_not_crash():
    P, N, H = cloud()
    H = H.copy(); H[::7] = np.nan; H[3] = np.inf
    N = N.copy(); N[5] = np.nan
    up = D.estimate_up(P, N, H)
    assert np.isfinite(up).all() and abs(up[2]) > 0.9


def test_principal_axes_needs_points():
    assert D._principal_axes(np.zeros((2, 3))) is None
    assert D._principal_axes(np.full((10, 3), np.nan)) is None
