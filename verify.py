#!/usr/bin/env python3
"""Independent printability checks on exported STLs: python verify.py out.stl [more.stl ...]"""
import sys, numpy as np, trimesh, manifold3d

for path in sys.argv[1:]:
    m = trimesh.load(path, process=False)
    mm = trimesh.Trimesh(m.vertices, m.faces, process=True)   # merge STL triangle soup
    print('==', path)
    print(f'  faces {len(mm.faces)}  watertight {mm.is_watertight}  winding-consistent {mm.is_winding_consistent}  is_volume {mm.is_volume}')
    print(f'  volume {mm.volume:.1f} mm3  bodies {mm.body_count}  euler {mm.euler_number}  genus {(2 - mm.euler_number) // 2 if mm.is_watertight else "n/a"}  (genus 0 = no tunnels)')
    mf = manifold3d.Manifold(manifold3d.Mesh(vert_properties=np.asarray(mm.vertices, np.float32), tri_verts=np.asarray(mm.faces, np.uint32)))
    print(f'  manifold3d: {mf.status()}  empty={mf.is_empty()}')
    # flat base: the largest group of coplanar faces (outputs keep the scan's original orientation, so the base is tilted)
    key = np.round(mm.face_normals, 3); u, inv = np.unique(key, axis=0, return_inverse=True)
    area = np.bincount(inv, weights=mm.area_faces); k = area.argmax(); sel = inv == k
    nrm = mm.face_normals[sel].mean(0); nrm /= np.linalg.norm(nrm)
    dist = mm.triangles_center[sel] @ nrm
    print(f'  flat base: area {area[k]:.0f} mm2, normal {np.round(nrm, 4).tolist()}, planarity spread {np.ptp(dist):.2e} mm, extents {np.round(mm.extents, 1).tolist()} mm')
    print(f'  degenerate faces (<1e-9 mm2): {int((mm.area_faces < 1e-9).sum())}')
    try:
        import pymeshlab
        ms = pymeshlab.MeshSet(); ms.load_new_mesh(path)
        ms.apply_filter('meshing_remove_duplicate_vertices')
        ms.apply_filter('compute_selection_by_self_intersections_per_face')
        n = ms.current_mesh().selected_face_number()
        print(f'  self-intersecting faces (MeshLab): {n}' + ('' if n == 0 else '   <-- slicer repair needed / inspect'))
    except Exception as e:
        print('  self-intersection check skipped (pip install pymeshlab; on Linux also: apt install libopengl0)')
