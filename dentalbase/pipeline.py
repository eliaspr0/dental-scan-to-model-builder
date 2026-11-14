"""End-to-end: raw intraoral scan STL -> watertight flat-base horseshoe dental model STL (geometry only, no ML)."""
import time, json
import numpy as np, trimesh, scipy.sparse as sp, scipy.sparse.csgraph as csg
from . import dbase


def log(t0, msg):
    print(f'[{time.time() - t0:5.1f}s] {msg}', flush=True)


def segment_crowns(V, F, H, beta=40.0, tau=0.0):
    """Tooth/gingiva probability from curvature barriers (random walker). Seeds: cusp tips vs. scan-border band."""
    n = len(V)
    A = dbase.mesh_adjacency(V, F)
    h = V[:, 2]
    cand = (H > np.percentile(H, 92)) & (h > np.percentile(h, 50))
    Ac = (A > 0).astype(np.int8)
    dil = cand.copy()
    for _ in range(3):
        dil = dil | ((Ac @ dil.astype(np.int8)) > 0)
    sub = Ac[dil][:, dil]
    nc, lab = csg.connected_components(sub, directed=False)
    sizes = np.bincount(lab); idx = np.where(dil)[0]
    big = np.isin(lab, np.where(sizes >= 300)[0])
    tooth_seed = np.zeros(n, bool); tooth_seed[idx[big]] = True; tooth_seed &= cand
    bv = np.zeros(n, bool); bv[dbase.boundary_vertices(F, n)] = True
    d_border = dbase.geodesic_from(V, F, bv)
    ging_seed = (d_border < 1.5) & ~tooth_seed
    p = dbase.random_walker(V, F, H, np.where(tooth_seed)[0], np.where(ging_seed)[0], beta=beta, tau=tau)
    return p, bv


def bridged_trim_field(V, F, mask, bv, offset, border_keepout, smooth_t, t0=None, max_rounds=6, min_tooth_area=2.0):
    """trim_field, but if the kept region splits into islands that contain teeth (edentulous gaps, small offsets,
    border keep-out), connect them to the main arch with a shortest surface path and use that path as an extra
    source so the base stays one continuous horseshoe."""
    n = len(V)
    A = dbase.mesh_adjacency(V, F)
    area = dbase.vertex_areas(V, F)
    src = mask.copy()
    d_border = dbase.geodesic_from(V, F, bv)
    pen = np.clip((border_keepout + 2.0 - d_border) / (border_keepout + 2.0), 0, 1)   # steer paths away from the ragged border
    Ac = A.tocoo()
    wts = Ac.data * (1.0 + 4.0 * 0.5 * (pen[Ac.row] + pen[Ac.col]))
    Aw = sp.coo_matrix((wts, (Ac.row, Ac.col)), shape=(n, n)).tocsr()
    bridges = 0
    for rnd in range(max_rounds):
        g, d_tooth, d_b = dbase.trim_field(V, F, src, bv, offset, border_keepout=border_keepout, smooth_t=smooth_t)
        neg = g < 0
        idx = np.where(neg)[0]
        nc, lab = csg.connected_components(A[neg][:, neg], directed=False)
        tooth_area = np.bincount(lab, weights=area[idx] * mask[idx], minlength=nc)
        order = np.argsort(-tooth_area)
        main = order[0]
        others = [k for k in order[1:] if tooth_area[k] >= min_tooth_area]
        if not others:
            break
        main_teeth = idx[(lab == main) & mask[idx]]
        k = others[0]
        k_teeth = idx[(lab == k) & mask[idx]]
        dist, pred, srcs = csg.dijkstra(Aw, directed=False, indices=k_teeth, return_predecessors=True, min_only=True)
        tgt = main_teeth[np.argmin(dist[main_teeth])]
        path = [tgt]
        while pred[path[-1]] >= 0 and path[-1] not in set(k_teeth.tolist()):
            path.append(pred[path[-1]])
        src[np.array(path)] = True
        bridges += 1
        if t0 is not None:
            log(t0, f'bridged tooth island {k} (tooth area {tooth_area[k]:.0f} mm2) to main arch: path {len(path)} verts, {dist[tgt]:.1f} mm')
    return g, d_tooth, d_b, bridges


def make_base(path_in, path_out, offset=4.0, smooth_t=6.0, loop_sigma=1.5, base_thickness=3.0,
              border_keepout=2.5, verbose=True, return_all=False):
    t0 = time.time()
    m = dbase.load_clean(path_in)
    V = np.asarray(m.vertices, float); F = np.asarray(m.faces)
    N = dbase.vertex_normals(m)
    log(t0, f'loaded {len(V)} verts / {len(F)} faces')
    H, _ = dbase.mean_curvature(V, F, N, t=0.15)
    up = dbase.estimate_up(V, N, H)
    R, c = dbase.orientation_frame(V, up)
    V = (V - c) @ R.T
    log(t0, f'occlusal normal {np.round(up, 3).tolist()}')
    p, bv = segment_crowns(V, F, H)
    mask = dbase.clean_tooth_mask(V, F, p)
    log(t0, f'tooth region {mask.sum()} verts')
    g, d_tooth, d_border, nbridge = bridged_trim_field(V, F, mask, bv, offset, border_keepout, smooth_t, t0=t0)
    V2, F2 = dbase.cut_mesh(V, F, g)
    mm = trimesh.Trimesh(V2, F2, process=False)
    comps = mm.split(only_watertight=False); comps.sort(key=lambda x: -len(x.faces))
    V2, F2 = np.asarray(comps[0].vertices), np.asarray(comps[0].faces)
    log(t0, f'trim cut: {len(F2)} faces, {len(dbase.boundary_loops(F2))} boundary loop(s)')
    D, maxd = dbase.smooth_trim_loop(V2, F2, sigma=loop_sigma)
    V3, alpha, it = dbase.safe_displace(V2, F2, D)
    log(t0, f'loop smoothed (max shift {maxd:.2f} mm, {int((alpha < 1).sum())} verts backed off)')
    # how much of the segmented crown area ended up inside the kept patch? (kept vertices = g<0 in the connected piece)
    area_all = dbase.vertex_areas(V, F)
    inside = (g < 0)
    kept_tooth = float(area_all[mask & inside].sum() / max(area_all[mask].sum(), 1e-9) * 100)
    Vb, Fb, info = dbase.build_base(V3, F2, base_thickness=base_thickness)
    out = trimesh.Trimesh(Vb, Fb, process=False)
    rep = dict(watertight=bool(out.is_watertight), winding_consistent=bool(out.is_winding_consistent),
               is_volume=bool(out.is_volume), volume_mm3=round(float(out.volume), 1), euler=int(out.euler_number),
               faces=int(len(Fb)), crown_area_kept_pct=round(kept_tooth, 1), bridges=int(nbridge), extents_mm=np.round(out.extents, 1).tolist(), **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in info.items()})
    out.export(path_out)
    log(t0, f'exported {path_out}: {rep}')
    if return_all:
        return rep, dict(V=V, F=F, H=H, p=p, mask=mask, g=g, Vcut=V3, Fcut=F2, Vb=Vb, Fb=Fb, R=R, c=c)
    return rep
