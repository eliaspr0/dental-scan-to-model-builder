import os, sys
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dentalbase.dbase import simple_outline, _crossing_pairs


def circle(n=400, r=20.0):
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.c_[r * np.cos(a), r * np.sin(a)]


def test_simple_outline_unchanged_when_already_simple():
    c = circle()
    assert np.array_equal(simple_outline(c), c)


def test_small_kink_loop_is_removed_and_rest_untouched():
    c = circle(1200)
    k = 300
    # a small kink: the outline steps back over itself for a few points (self-crossing hairpin)
    kink = c.copy()
    kink[k + 3:k + 7] = kink[k - 2:k + 2][::-1] + np.array([0.0, 0.05])
    assert _crossing_pairs(kink), 'test setup must contain a crossing'
    out = simple_outline(kink)
    assert not _crossing_pairs(out)
    far = np.ones(len(c), bool); far[max(k - 150, 0):k + 150] = False
    assert np.array_equal(out[far], kink[far])
