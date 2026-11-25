"""End-to-end: raw intraoral scan STL -> watertight flat-base horseshoe dental model STL (geometry only, no ML).

Guarantees (checked after every export, see check_tooth_preservation):
  * Output is written in the INPUT scan's own coordinate system, so an upper and lower scan that were articulated
    (bite registered) in the same frame stay articulated.
  * Tooth geometry is never modified: crown vertices (plus a small margin ring) are copied bit-for-bit from the
    input, never moved by smoothing and never cut away.
"""
import time, json
import os
import numpy as np, trimesh, scipy.sparse as sp, scipy.sparse.csgraph as csg
from scipy.spatial import cKDTree
import igl
from . import dbase


def log(t0, msg):
    print(f'[{time.time() - t0:5.1f}s] {msg}', flush=True)


STAGES = ['Reading the scan', 'Finding the bite plane', 'Finding the teeth', 'Marking the trimline',
          'Smoothing the trimline', 'Building the base', 'Saving and checking']


def stage(i, verbose=True):
    """Machine-readable progress line (the GUI parses it): @@STAGE <i>/<n> <label>"""
    if verbose:
        print(f'@@STAGE {i}/{len(STAGES)} {STAGES[i - 1]}', flush=True)


# "Second look" for teeth the curvature seeds miss (see segment_crowns)
TOOTH_RISE_MM = 6.0   # a vertex this far above the local gum level counts as tooth...
TOOTH_CORE_MM = 1.0   # ...if it is also this far inside such a tall region,
TOOTH_FACING = 0.75   # ...faces up (chewing surface, not a steep gum slope),
TOOTH_SLICES = 120    # ...and lies in a part of the arch (cross-section) where
TOOTH_COVER = 0.4     # less than this share of what stands tall was already found as tooth


def segment_crowns(V, F, H, beta=40.0, tau=0.0):
    n = len(V)
    A = dbase.mesh_adjacency(V, F)
    h = V[:, 2]
    # Ragged scan borders / spiky triangles carry huge curvature values that are
    # not teeth. Measure the thresholds on the interior only and never seed there.
    bv = np.zeros(n, bool); bv[dbase.boundary_vertices(F, n)] = True
    d_border = dbase.geodesic_from(V, F, bv)
    interior = d_border > 2.0
    # spike vertices (degenerate/folded triangles) have |H| orders of magnitude above any real tooth surface
    spike = np.abs(H) > 20.0
    Asp = (dbase.mesh_adjacency(V, F) > 0).astype(np.int8)
    for _ in range(2):
        spike = spike | ((Asp @ spike.astype(np.int8)) > 0)
    interior &= ~spike
    if interior.sum() < 0.2 * n:
        interior = np.ones(n, bool)
    cand = (H > np.percentile(H[interior], 92)) & (h > np.percentile(h[interior], 50)) & interior
    Ac = (A > 0).astype(np.int8)
    dil = cand.copy()
    for _ in range(3):
        dil = dil | ((Ac @ dil.astype(np.int8)) > 0)
    sub = Ac[dil][:, dil]
    nc, lab = csg.connected_components(sub, directed=False)
    sizes = np.bincount(lab); idx = np.where(dil)[0]
    big = np.isin(lab, np.where(sizes >= 300)[0])
    tooth_seed = np.zeros(n, bool); tooth_seed[idx[big]] = True; tooth_seed &= cand
    ging_seed = (d_border < 1.5) & ~tooth_seed
    p = dbase.random_walker(V, F, H, np.where(tooth_seed)[0], np.where(ging_seed)[0], beta=beta, tau=tau)
    # Second look. Teeth with no strong curvature peak (flat/worn molars at the far end of the scan, an implant scan body)
    # got no seed above and are labelled gum. If a part of the arch has no tooth at all yet something there stands several
    # mm above the gum, seed it as tooth and run the walker again. Parts of the arch that already contain teeth are left
    # exactly as before (so well-detected scans do not change).
    ns = TOOTH_SLICES
    sl = dbase.arch_slices(V, ns)
    rise = dbase.height_above_gum(V)
    n_tooth = np.bincount(sl[p > 0.5], minlength=ns).astype(float)
    n_tall = np.bincount(sl[(rise > TOOTH_RISE_MM) & interior], minlength=ns).astype(float)
    covered = n_tooth >= TOOTH_COVER * np.maximum(n_tall, 1.0)    # most of what stands tall here is already tooth
    tall = (rise > TOOTH_RISE_MM) & interior & ~covered[sl]
    d_edge = dbase.geodesic_from(V, F, ~tall)                  # distance to the edge of the tall region
    up_facing = np.asarray(igl.per_vertex_normals(V, F))[:, 2] > TOOTH_FACING    # chewing surfaces face up
    core = tall & (d_edge > TOOTH_CORE_MM) & up_facing
    if core.any():
        nct, labt = csg.connected_components(Ac[core][:, core], directed=False)
        big_t = np.isin(labt, np.where(np.bincount(labt) >= 300)[0])
        extra = np.zeros(n, bool); extra[np.where(core)[0][big_t]] = True
        if extra.any():
            seeds = tooth_seed | extra
            p = dbase.random_walker(V, F, H, np.where(seeds)[0], np.where(ging_seed & ~extra)[0], beta=beta, tau=tau)
    return p, bv


def bridged_trim_field(V, F, mask, bv, offset, border_keepout, smooth_t, t0=None, max_rounds=6, min_tooth_area=2.0,
                       protect_mm=None):
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
        g, d_tooth, d_b = dbase.trim_field(V, F, src, bv, offset, border_keepout=border_keepout, smooth_t=smooth_t,
                                           protect_mm=protect_mm)
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


def keep_largest_component(V, F, oid):
    """Keep the largest connected piece (by faces); returns reindexed V, F, oid."""
    n = len(V)
    A = sp.coo_matrix((np.ones(len(F) * 3), (np.r_[F[:, 0], F[:, 1], F[:, 2]], np.r_[F[:, 1], F[:, 2], F[:, 0]])), shape=(n, n))
    nc, lab = csg.connected_components(A, directed=False)
    if nc == 1:
        return V, F, oid
    fl = lab[F[:, 0]]
    big = np.bincount(fl).argmax()
    Fk = F[fl == big]
    used = np.unique(Fk); remap = -np.ones(n, np.int64); remap[used] = np.arange(len(used))
    return V[used], remap[Fk], oid[used]


def resample_closed_xy(P, h):
    """Resample a closed polyline every h mm (plan view), starting at P[0]."""
    seg = np.linalg.norm(np.roll(P, -1, 0) - P, axis=1); s = np.r_[0, np.cumsum(seg)]
    su = np.linspace(0, s[-1], max(int(round(s[-1] / h)), 8), endpoint=False)
    Pc = np.vstack([P, P[:1]])
    return np.column_stack([np.interp(su, s, Pc[:, k]) for k in range(2)])


def estimate_arch_up(path_in):
    """Occlusal-plane normal (gingiva -> crowns) of one scan, in the scan's own coordinates."""
    m = dbase.load_clean(path_in)
    V = np.asarray(m.vertices, float); F = np.asarray(m.faces)
    if not len(dbase.boundary_vertices(F, len(V))):
        raise ScanError(os.path.basename(path_in) + ': ' + CLOSED_MSG)
    N = dbase.vertex_normals(m)
    H, _ = dbase.mean_curvature(V, F, N, t=0.15)
    return dbase.estimate_up(V, N, H)


def check_tooth_preservation(V0, mask, out_path, extra_mask=None):
    """Reload the exported STL and compare against the ORIGINAL scan vertices. Returns exactness stats."""
    o = trimesh.load(out_path, process=False)
    Vo = np.asarray(o.vertices, np.float64)
    tree = cKDTree(Vo)
    rep = {}
    for name, mk in (('crown', mask), ('crown_plus_margin', extra_mask)):
        if mk is None or not mk.any():
            continue
        P = V0[mk].astype(np.float32).astype(np.float64)       # STL stores float32
        d, _ = tree.query(P)
        rep[f'{name}_vertices'] = int(mk.sum())
        rep[f'{name}_exact_pct'] = round(float((d == 0).mean() * 100), 4)
        rep[f'{name}_max_dev_mm'] = round(float(d.max()), 6)
    return rep


class ScanError(ValueError):
    """The input file cannot be used (message is meant for the user)."""


CLOSED_MSG = ('this file has no open edge: it is already a closed model (for example an earlier _output file). '
              'Please use the original raw scan.')


def make_base(path_in, path_out, offset=4.5, smooth_t=6.0, loop_sigma=2.0, base_thickness=0.5,
              border_keepout=2.5, protect_mm=None, up=None, trim_mode='base', strip=None, strip_min=1.0, verbose=True, return_all=False,
              follow_tips=False, max_tilt_deg=10.0, offset_lingual=None, follow_gum=False, max_gum_tilt_deg=30.0, follow_mid=False):
    """up: optional occlusal normal (gingiva->crowns) in the scan's own coordinates, e.g. a shared bite-plane normal
    for an upper/lower pair. protect_mm: crowns + this ring are guaranteed untouched (default min(1, offset/2));
    pass a negative value to disable (for A/B testing only).
    follow_tips: make the flat base parallel to the tooth tips (plane through the incisal edges / cusp tips of the crowns)
    instead of the estimated bite plane; ignored (with a note) if that plane differs by more than max_tilt_deg."""
    t0 = time.time()
    dbase.clear_cache()                     # per-mesh caches only live for one job
    if protect_mm is None:
        protect_mm = min(1.0, 0.5 * (offset if offset_lingual is None else min(offset, offset_lingual)))
    stage(1, verbose)
    m = dbase.load_clean(path_in)
    V0 = np.asarray(m.vertices, float); F = np.asarray(m.faces)      # ORIGINAL coordinates: never modified
    N = dbase.vertex_normals(m)
    log(t0, f'loaded {len(V0)} verts / {len(F)} faces')
    if not len(dbase.boundary_vertices(F, len(V0))):
        raise ScanError(CLOSED_MSG)
    H, _ = dbase.mean_curvature(V0, F, N, t=0.15)
    stage(2, verbose)
    if up is None:
        up = dbase.estimate_up(V0, N, H)
    else:
        up = np.asarray(up, float) / np.linalg.norm(up)
    R, c = dbase.orientation_frame(V0, up)
    V = (V0 - c) @ R.T                                                # working frame (Z = occlusal normal)
    log(t0, f'occlusal normal (scan coords) {np.round(up, 3).tolist()}')
    stage(3, verbose)
    p, bv = segment_crowns(V, F, H)
    mask = dbase.clean_tooth_mask(V, F, p)
    log(t0, f'tooth region {mask.sum()} verts')
    tilt_deg = 0.0
    if follow_tips:
        nt, tinfo = dbase.tip_plane_normal(V, mask)
        if nt is None:
            log(t0, f'base follows the bite plane (tooth-tip plane unavailable: {tinfo})')
        else:
            tilt_deg = float(np.degrees(np.arccos(np.clip(nt[2], -1, 1))))
            if tilt_deg > max_tilt_deg:
                log(t0, f'base follows the bite plane (tooth-tip plane is {tilt_deg:.1f} deg away, limit {max_tilt_deg:g} deg)')
                tilt_deg = 0.0
            else:
                R2 = dbase.tilt_rotation(nt)
                V = V @ R2.T                                      # re-orient the working frame; mask/p/bv are per-vertex, still valid
                R = R2 @ R
                log(t0, f"base follows the tooth tips: tilted {tilt_deg:.1f} deg from the bite plane ({tinfo['tips']}/{tinfo['tips_total']} arch slices, fit rms {tinfo['rms_mm']:.2f} mm)")
    pm = protect_mm if protect_mm >= 0 else None
    stage(4, verbose)
    offset_field = offset
    if offset_lingual is not None and abs(offset_lingual - offset) > 1e-9:
        side = dbase.arch_side(V, mask)                      # +1 labial/buccal ... -1 lingual/palatal
        offset_field = offset * (1 + side) / 2 + offset_lingual * (1 - side) / 2
        log(t0, f'margin height: {offset:g} mm labial / buccal, {offset_lingual:g} mm lingual / palatal')
    g, d_tooth, d_border, nbridge = bridged_trim_field(V, F, mask, bv, offset_field, border_keepout, smooth_t, t0=t0, protect_mm=pm)
    if (follow_gum or follow_mid) and not follow_tips:
        # the cut line does not depend on the base direction: cut once in the bite frame, fit a plane to the trimline, tilt the frame to it
        Vg, Fg, _ = dbase.cut_mesh(V, F, g)
        Vg, Fg, _ = keep_largest_component(Vg, Fg, np.arange(len(Vg)))
        ng, ginfo = dbase.gum_plane_normal(Vg, Fg)
        if follow_mid and ng is not None:
            nt_m, tinfo_m = dbase.tip_plane_normal(V, mask)
            if nt_m is None:
                log(t0, f'tooth-tip plane unavailable ({tinfo_m}): using the gum line alone')
            else:
                ng = ng + nt_m                                    # halfway between the tooth-tip plane and the gum-line plane
                ng /= np.linalg.norm(ng)
        if ng is None:
            log(t0, f'base follows the bite plane (gum line unavailable: {ginfo})')
        else:
            tilt_deg = float(np.degrees(np.arccos(np.clip(ng[2], -1, 1))))
            if tilt_deg > max_gum_tilt_deg:
                log(t0, f'base follows the bite plane (gum-line plane is {tilt_deg:.1f} deg away, limit {max_gum_tilt_deg:g} deg)')
                tilt_deg = 0.0
            else:
                R2 = dbase.tilt_rotation(ng)
                V = V @ R2.T
                R = R2 @ R
                log(t0, f"base follows the {'tips and gum line (halfway)' if follow_mid else 'gum line'}: tilted {tilt_deg:.1f} deg from the bite plane (trimline height spread {ginfo['spread_mm']:.1f} mm, fit rms {ginfo['rms_mm']:.2f} mm)")
    V2, F2, oid = dbase.cut_mesh(V, F, g)
    V2, F2, oid = keep_largest_component(V2, F2, oid)
    F2, dropped = dbase.drop_nonmanifold_faces(F2)
    if dropped:
        log(t0, f'removed {dropped} faces around a fold in the raw scan (an edge shared by more than two faces); no vertex moved')
    F2, holes = dbase.fill_small_holes(V2, F2)
    orphan_orig = np.array([], int)
    if dropped:                       # vertices that only belonged to the removed fold faces are no geometry: nothing left to keep
        orphan = np.setdiff1d(np.arange(len(V2)), np.unique(F2))
        orphan_orig = oid[orphan][oid[orphan] >= 0]
    if holes['filled'] or holes['skipped']:
        log(t0, f"closed {holes['filled']} small hole(s) in the scan surface (longest edge {holes['largest_mm']} mm); no vertices moved"
                + (f", {holes['skipped']} too large to close" if holes['skipped'] else ''))
    log(t0, f'trim cut: {len(F2)} faces, {len(dbase.boundary_loops(F2))} boundary loop(s)')
    prot_full = ((d_tooth <= protect_mm) | mask) if protect_mm >= 0 else np.zeros(len(V), bool)   # crowns always pinned (even isolated islands)
    stage(5, verbose)
    bottom_path = None
    if trim_mode == 'base':
        # Smooth wall (default). The trimline is smoothed in 3D (outline and height, sigma = loop_sigma) and the vertical
        # wall is extruded straight down from it. The scan follows the edge only inside a fade strip along the cut: a
        # biharmonic fade brings the shift to zero (with zero slope) at the strip's outer border, so it blends into the
        # untouched scan. The strip is `strip_min` (1 mm) wide where the edge shifts noticeably, never narrower than 2x the local
        # shift, narrows toward zero where it barely moves, and widens only if triangles would fold.
        # Everything farther from the edge is bit-exact.
        prot_cut = np.zeros(len(V2), bool); ok = oid >= 0; prot_cut[ok] = prot_full[oid[ok]]
        prot_arg = prot_cut if protect_mm >= 0 else None
        Lm_, Ls_ = dbase.smoothed_loop_positions(V2, F2, loop_sigma)
        shift = float(np.linalg.norm(Ls_ - V2[Lm_], axis=1).max())
        strip = strip_min if strip is None else strip      # blend width: where the edge shifts noticeably; narrower elsewhere
        best = None                                       # (backed-off vertices, strip, V3, alpha, D, maxd)
        for strip_try in (strip, 1.5 * strip, 2.0 * strip):
            D, maxd = dbase.fade_trimline(V2, F2, loop_sigma, strip_try, protect=prot_arg, zmove=True)
            V3, alpha, it = dbase.safe_displace(V2, F2, D)
            nb_ = int((alpha < 1).sum())
            if best is None or nb_ < 0.9 * best[0]:       # a wider strip must clearly reduce the triangle back-offs
                best = (nb_, strip_try, V3, alpha, D, maxd)
            if nb_ == 0 or best[1] != strip_try:
                break
        nb_, strip_used, V3, alpha, D, maxd = best
        D = V3 - V2
        bottom_path = resample_closed_xy(V3[dbase.main_loop(F2)[0]][:, :2], 0.3)   # evenly spaced, same curve: clean cap, vertical wall
        moved = int((np.abs(D).sum(1) > 0).sum())
        log(t0, f'trimline smoothed (sigma {loop_sigma:g} mm, max edge shift {maxd:.2f} mm); blend width {strip_used:g} mm (narrower where the edge barely moves) '
                f'({moved} vertices moved, {nb_} backed off); surface beyond the strip untouched')
    else:                                                               # legacy 'deform' mode: also blends the shift into the surface
        prot_cut = np.zeros(len(V2), bool); ok = oid >= 0; prot_cut[ok] = prot_full[oid[ok]]
        D, maxd = dbase.smooth_trim_loop(V2, F2, sigma=loop_sigma, protect=prot_cut if protect_mm >= 0 else None)
        V3, alpha, it = dbase.safe_displace(V2, F2, D)
        log(t0, f'loop smoothed (max shift {maxd:.2f} mm, {int((alpha < 1).sum())} verts backed off)')
    stage(6, verbose)
    try:
        Vb, Fb, info = dbase.build_base(V3, F2, base_thickness=base_thickness, bottom_path=bottom_path)
    except AssertionError as e:
        raise ScanError('The scan has an open area that could not be closed automatically (' + str(e) + '). '
                        'Close the large holes in the scan first (for example in your scanner software), then try again.') from None
    stage(7, verbose)
    # ---- back to the scan's original coordinate system (keeps upper/lower articulation)
    Vb_o = Vb @ R + c
    untouched = np.where((oid >= 0) & (np.abs(D).sum(1) == 0))[0]     # never displaced -> copy original coords bit-exactly
    Vb_o[untouched] = V0[oid[untouched]]
    out = trimesh.Trimesh(Vb_o, Fb, process=False)
    out.export(path_out)
    area_all = dbase.vertex_areas(V, F)
    kept = np.zeros(len(V), bool); kept[oid[oid >= 0]] = True
    kept_tooth = float(area_all[mask & kept].sum() / max(area_all[mask].sum(), 1e-9) * 100)
    rep = dict(watertight=bool(out.is_watertight), winding_consistent=bool(out.is_winding_consistent),
               is_volume=bool(out.is_volume), volume_mm3=round(float(out.volume), 1), euler=int(out.euler_number),
               faces=int(len(Fb)), crown_area_kept_pct=round(kept_tooth, 2), bridges=int(nbridge),
               extents_mm=np.round(out.extents, 1).tolist(), occlusal_normal=np.round(up, 4).tolist(), base_tilt_deg=round(tilt_deg, 2),
               **{k: (round(v, 2) if isinstance(v, float) else v) for k, v in info.items() if k != 'z_base'})
    chk_mask = mask.copy(); chk_prot = prot_full.copy()
    chk_mask[orphan_orig] = False; chk_prot[orphan_orig] = False
    if len(orphan_orig):
        rep['fold_vertices_dropped'] = int(len(orphan_orig))
    rep.update(check_tooth_preservation(V0, chk_mask, path_out, chk_prot if protect_mm >= 0 else None))
    log(t0, f'exported {path_out}: {rep}')
    if return_all:
        return rep, dict(V0=V0, V=V, F=F, H=H, p=p, mask=mask, g=g, Vb=Vb_o, Fb=Fb, R=R, c=c, oid=oid, D=D, prot=prot_full)
    return rep


def make_pair(upper_in, lower_in, upper_out, lower_out, **kw):
    """Articulated pair: both bases are made parallel to the shared bite (occlusal) plane and both outputs stay in the
    original (registered) coordinate system. Returns (upper_report, lower_report)."""
    up_u = estimate_arch_up(upper_in)      # points from upper gingiva toward upper crowns (= downward)
    up_l = estimate_arch_up(lower_in)      # points from lower gingiva toward lower crowns (= upward)
    n = up_l - up_u
    n /= np.linalg.norm(n)
    ang = float(np.degrees(np.arccos(np.clip(up_l @ -up_u, -1, 1))))
    print(f'shared occlusal normal {np.round(n, 3).tolist()} (upper/lower estimates differ by {ang:.1f} deg)')
    if ang > 15:
        print('  WARNING: the two arches disagree on the occlusal plane by >15 deg; are the scans bite-registered in one frame?')
    ru = make_base(upper_in, upper_out, up=-n, **kw)
    rl = make_base(lower_in, lower_out, up=n, **kw)
    ru['arch_plane_disagreement_deg'] = rl['arch_plane_disagreement_deg'] = round(ang, 2)
    return ru, rl
