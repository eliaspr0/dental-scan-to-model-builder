"""Second look for missed teeth: height above the gum and arch cross-sections."""
import numpy as np
from dentalbase import dbase


def _arch(n=40000, seed=0):
    """Horseshoe point cloud: low gum on both sides, one tall bump (a tooth) in the middle of the cross-section
    for arch angles 60-90 deg, and a steep gum ridge elsewhere."""
    rs = np.random.RandomState(seed)
    th = rs.uniform(0.1 * np.pi, 0.9 * np.pi, n)
    r = rs.uniform(14, 28, n)                              # across the arch: inner (tongue) ... outer (cheek)
    z = 1.0 + 0.04 * (r - 14)                              # gently sloping gum
    tooth = (th > 0.33 * np.pi) & (th < 0.5 * np.pi) & (r > 18) & (r < 24)
    z = np.where(tooth, 9.0 - 0.5 * np.abs(r - 21), z)
    return np.c_[r * np.cos(th), r * np.sin(th), z], tooth


def test_tooth_stands_tall_gum_does_not():
    V, tooth = _arch()
    rise = dbase.height_above_gum(V)
    assert np.median(rise[tooth]) > 5.0
    assert np.median(rise[~tooth]) < 3.0


def test_slices_cover_the_arch_in_order():
    V, _ = _arch()
    s = dbase.arch_slices(V, 60)
    assert s.min() == 0 and s.max() == 59
    c = V[:, :2].mean(0)
    ang = np.arctan2(V[:, 1] - c[1], V[:, 0] - c[0])
    # slices follow the arch: neighbouring angles fall into the same or the next slice (one jump where numbering starts)
    d = np.abs(np.diff(s[np.argsort(ang)]))
    assert np.mean(d <= 1) > 0.99


def test_flat_scan_gives_no_height():
    V, _ = _arch()
    V[:, 2] = 1.0
    assert np.abs(dbase.height_above_gum(V)).max() < 1e-6
