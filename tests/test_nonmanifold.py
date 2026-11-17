"""Raw-scan folds (an edge shared by 4 faces) are removed; hole fill never creates a doubled edge."""
import numpy as np
from dentalbase import dbase


def test_drop_faces_around_edge_with_four_faces():
    F = np.array([[0, 1, 2], [1, 0, 3], [0, 1, 4], [1, 0, 5], [6, 7, 8]])      # edge 0-1 is in four faces
    G, n = dbase.drop_nonmanifold_faces(F)
    assert n == 4 and G.tolist() == [[6, 7, 8]]


def test_clean_mesh_is_untouched():
    F = np.array([[0, 1, 2], [1, 3, 2]])
    G, n = dbase.drop_nonmanifold_faces(F)
    assert n == 0 and (G == F).all()


def test_hole_fill_avoids_existing_chord():
    # square hole 0-1-2-3 (counter-clockwise), but the scan already has an edge 0-2 elsewhere
    Q = np.array([[0.0, 0], [1, 0], [1, 1], [0, 1]])
    vid = np.array([10, 11, 12, 13])
    T = np.array([[0, 1, 2], [0, 2, 3]])                       # uses chord 0-2 (ids 10-12)
    existing = {(10, 12)}
    T2 = dbase._avoid_existing_chords(T, Q, vid, existing)
    chords = {tuple(sorted((int(vid[a]), int(vid[b])))) for t in T2 for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0]))
              if (a - b) % 4 not in (1, 3)}
    assert not (chords & existing) and len(T2) == 2
