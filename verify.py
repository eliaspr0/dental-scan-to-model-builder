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
    z = mm.vertices[:, 2]
    print(f'  flat base vertices at zmin: {int(np.isclose(z, z.min(), atol=1e-6).sum())}  extents {np.round(mm.extents, 1).tolist()} mm')
    print(f'  degenerate faces (<1e-9 mm2): {int((mm.area_faces < 1e-9).sum())}')
