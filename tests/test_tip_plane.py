"""Tooth-tip plane: finds the slope of the cusp tips, and the rotation maps it to +Z."""
import numpy as np
from dentalbase import dbase


def _arch(slope_x=0.0, slope_y=0.0, n=6000, seed=0):
    rs = np.random.RandomState(seed)
    th = rs.uniform(0.15 * np.pi, 0.85 * np.pi, n)            # horseshoe, open toward -y
    r = 22 + rs.normal(0, 1.2, n)
    x, y = r * np.cos(th), r * np.sin(th)
    z = 5 + 1.5 * np.sin(6 * th) + rs.normal(0, 0.2, n)        # cusps
    z = z + slope_x * x + slope_y * y                         # tip plane tilted
    return np.c_[x, y, z]


def test_recovers_tilt():
    V = _arch(0.0, 0.07)                                      # ~4 deg about X
    nt, info = dbase.tip_plane_normal(V, np.ones(len(V), bool))
    assert nt is not None
    want = np.array([0, -0.07, 1.0]); want /= np.linalg.norm(want)
    assert np.degrees(np.arccos(np.clip(nt @ want, -1, 1))) < 1.0


def test_flat_arch_is_not_tilted():
    V = _arch()
    nt, _ = dbase.tip_plane_normal(V, np.ones(len(V), bool))
    assert np.degrees(np.arccos(nt[2])) < 1.0


def test_outlier_spike_is_ignored():
    V = _arch(0.0, 0.05)
    V[:40, 2] += 30                                           # a few stray high points
    nt, _ = dbase.tip_plane_normal(V, np.ones(len(V), bool))
    assert np.degrees(np.arccos(nt[2])) < 5.0


def test_too_few_points():
    nt, why = dbase.tip_plane_normal(_arch(n=100), np.ones(100, bool))
    assert nt is None and isinstance(why, str)


def test_rotation_maps_normal_to_z():
    n = np.array([0.1, -0.12, 0.98]); n /= np.linalg.norm(n)
    R = dbase.tilt_rotation(n)
    assert np.allclose(R @ n, [0, 0, 1], atol=1e-9)
    assert np.allclose(R @ R.T, np.eye(3), atol=1e-9) and abs(np.linalg.det(R) - 1) < 1e-9
    assert np.allclose(dbase.tilt_rotation([0, 0, 1]), np.eye(3))
