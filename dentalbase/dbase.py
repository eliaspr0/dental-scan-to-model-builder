"""Geometry-only dental base prototype: load/clean, orient, curvature, margin field."""
import numpy as np, trimesh, igl, scipy.sparse as sp
from scipy.sparse.linalg import splu


def load_clean(path):
    m = trimesh.load(path, process=False)
    m.merge_vertices()
    m.update_faces(m.nondegenerate_faces())
    m.update_faces(m.unique_faces())
    m.remove_unreferenced_vertices()
    # keep largest component
    comps = m.split(only_watertight=False)
    comps.sort(key=lambda c: -len(c.faces))
    m = comps[0]
    trimesh.repair.fix_normals(m)
    return m


def vertex_normals(m):
    return np.asarray(m.vertex_normals)


def cot_laplacian(V, F):
    L = -igl.cotmatrix(V, F)      # positive semi-definite
    M = igl.massmatrix(V, F, igl.MASSMATRIX_TYPE_VORONOI)
    return L.tocsc(), M.tocsc()


def smooth_scalar(V, F, f, t):
    """Implicit heat-flow smoothing of a per-vertex scalar, diffusion time t (mm^2)."""
    L, M = cot_laplacian(V, F)
    A = (M + t * L).tocsc()
    lu = splu(A)
    return lu.solve(M @ f)


def mean_curvature(V, F, N, t=0.15):
    """Signed mean curvature (positive = convex w.r.t. outward normal) on a heat-smoothed surface."""
    L, M = cot_laplacian(V, F)
    A = (M + t * L).tocsc()
    lu = splu(A)
    Vs = np.column_stack([lu.solve(M @ V[:, i]) for i in range(3)])
    Ls, Ms = cot_laplacian(Vs, F)
    Hn = -(Ls @ Vs)                      # = 2 * H * n * area  (mean curvature normal * mass)
    area = np.asarray(Ms.sum(axis=1)).ravel()
    Hn = Hn / area[:, None]
    # sign: mean curvature vector points inward for convex surface (with outward normal)
    Ns = igl.per_vertex_normals(Vs, F)
    H = -0.5 * np.einsum('ij,ij->i', Hn, Ns)
    return H, Vs


def estimate_up(V, N, H, iters=3):
    """Occlusal-plane normal (pointing from gingiva toward the crowns) from geometry only."""
    c = V.mean(0)
    # initial: smallest PCA axis, sign from mean outward normal
    w, U = np.linalg.eigh(np.cov((V - c).T))
    up = U[:, 0]
    if np.dot(up, N.mean(0)) < 0:
        up = -up
    for _ in range(iters):
        h = (V - c) @ up
        # cusp tips / incisal edges: strongly convex AND high
        sel = (H > np.percentile(H, 92)) & (h > np.percentile(h, 55))
        P = V[sel]
        cc = P.mean(0)
        # plane fit to those points (least squares) -> normal = smallest axis
        _, Uc = np.linalg.eigh(np.cov((P - cc).T))
        n = Uc[:, 0]
        if np.dot(n, up) < 0:
            n = -n
        up = n / np.linalg.norm(n)
    return up


def orientation_frame(V, up):
    """Rotation R (rows = new axes) so that up -> +Z, arch long axis -> X, centered at arch centroid."""
    up = up / np.linalg.norm(up)
    c = V.mean(0)
    P = V - c
    P2 = P - np.outer(P @ up, up)
    w, U = np.linalg.eigh(np.cov(P2.T))
    # two largest in-plane axes: those orthogonal to up
    cand = [U[:, i] for i in range(3)]
    cand.sort(key=lambda a: -abs(np.dot(a, up)))  # last two are in-plane-ish
    a1 = cand[2] - np.dot(cand[2], up) * up
    a1 /= np.linalg.norm(a1)
    a2 = np.cross(up, a1)
    R = np.vstack([a1, a2, up])
    return R, c


# ---------------------------------------------------------------- margin field
import scipy.sparse.csgraph as csg
from scipy.sparse.linalg import spsolve


def mesh_adjacency(V, F, weights='len'):
    he = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    he = np.sort(he, axis=1)
    he = np.unique(he, axis=0)
    l = np.linalg.norm(V[he[:, 0]] - V[he[:, 1]], axis=1)
    n = len(V)
    A = sp.coo_matrix((l, (he[:, 0], he[:, 1])), shape=(n, n))
    return (A + A.T).tocsr()


def boundary_vertices(F, n):
    he = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    s = np.sort(he, axis=1)
    key = s[:, 0].astype(np.int64) * n + s[:, 1]
    u, inv, cnt = np.unique(key, return_inverse=True, return_counts=True)
    b = he[cnt[inv] == 1]
    return np.unique(b.ravel())


def geodesic_from(V, F, src_mask):
    """Approximate geodesic distance (mm) from a vertex set (Dijkstra on edge graph + heat-method fallback)."""
    import potpourri3d as pp3d
    solver = pp3d.MeshHeatMethodDistanceSolver(V, F)
    return solver.compute_distance_multisource(np.where(src_mask)[0])


def random_walker(V, F, H, tooth_seeds, gingiva_seeds, beta=6.0, tau=0.15):
    """Edge weights suppressed across concave creases (H < -tau). Returns P(tooth) per vertex."""
    n = len(V)
    he = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    he = np.unique(np.sort(he, axis=1), axis=0)
    i, j = he[:, 0], he[:, 1]
    l = np.linalg.norm(V[i] - V[j], axis=1)
    Hc = np.clip(H, -4.0, 4.0)
    conc = np.clip(-(0.5 * (Hc[i] + Hc[j])) - tau, 0.0, 3.0)
    w = (np.exp(-beta * conc) + 1e-6) / np.maximum(l, 0.05)
    W = sp.coo_matrix((w, (i, j)), shape=(n, n))
    W = (W + W.T).tocsr()
    d = np.asarray(W.sum(1)).ravel()
    Lm = (sp.diags(d) - W).tocsr()
    seeds = np.zeros(n, bool); seeds[tooth_seeds] = True; seeds[gingiva_seeds] = True
    u = np.where(~seeds)[0]
    s = np.where(seeds)[0]
    xs = np.zeros(n); xs[tooth_seeds] = 1.0
    Luu = Lm[u][:, u].tocsc()
    rhs = -Lm[u][:, s] @ xs[s]
    xu = splu(Luu).solve(rhs)
    p = xs.copy(); p[u] = xu
    return p


# ---------------------------------------------------------------- isolines
def isoline_segments(V, F, f, level):
    """Return list of segments (2x3 arrays) where scalar f crosses level, as (edge_key pairs, points)."""
    g = f - level
    s = g[F] > 0                         # (nf,3) sign
    cross = (s.sum(1) == 1) | (s.sum(1) == 2)
    Fi = F[cross]; gi = g[Fi]; si = s[cross]
    pts, keys = [], []
    for k in range(3):
        a = Fi[:, k]; b = Fi[:, (k + 1) % 3]
        ga = g[a]; gb = g[b]
        m = (ga > 0) != (gb > 0)
        t = np.where(m, ga / (ga - gb + 1e-300), 0.0)
        P = V[a] + (V[b] - V[a]) * t[:, None]
        pts.append((P, m, np.minimum(a, b), np.maximum(a, b)))
    segs = []
    for r in range(len(Fi)):
        e = [(pts[k][0][r], pts[k][2][r], pts[k][3][r]) for k in range(3) if pts[k][1][r]]
        if len(e) == 2:
            segs.append(e)
    return segs


def chain_segments(segs):
    """Link segments into polylines/loops by shared edge keys. Returns list of (points Nx3, closed bool)."""
    from collections import defaultdict
    adj = defaultdict(list)
    P = {}
    for si, (a, b) in enumerate(segs):
        ka = (int(a[1]), int(a[2])); kb = (int(b[1]), int(b[2]))
        P[ka] = a[0]; P[kb] = b[0]
        adj[ka].append((kb, si)); adj[kb].append((ka, si))
    used = set(); out = []
    for start in list(adj):
        if len(adj[start]) != 1:
            continue
        # open chain start
        chain = [start]; cur = start; prev_s = None
        while True:
            nxt = [x for x in adj[cur] if x[1] != prev_s and x[1] not in used]
            if not nxt: break
            k, si = nxt[0]; used.add(si); chain.append(k); prev_s = si; cur = k
        out.append((np.array([P[k] for k in chain]), False))
    for start in list(adj):
        if all(si in used for _, si in adj[start]):
            continue
        chain = [start]; cur = start; prev_s = None
        while True:
            nxt = [x for x in adj[cur] if x[1] != prev_s and x[1] not in used]
            if not nxt: break
            k, si = nxt[0]; used.add(si); chain.append(k); prev_s = si; cur = k
            if k == start: break
        out.append((np.array([P[k] for k in chain]), chain[0] == chain[-1] and len(chain) > 2))
    return out


# ---------------------------------------------------------------- trimline field + cutting
def vertex_areas(V, F):
    return np.asarray(igl.massmatrix(V, F, igl.MASSMATRIX_TYPE_VORONOI).diagonal())


def clean_tooth_mask(V, F, p, thresh=0.5, min_area=4.0):
    """Tooth mask from P(tooth): drop tiny islands (mm^2), fill small gingiva holes inside crowns."""
    n = len(V)
    A = mesh_adjacency(V, F)
    area = vertex_areas(V, F)
    mask = p > thresh
    for flag in (True, False):               # remove tooth islands, then fill gingiva islands
        sel = mask if flag else ~mask
        sub = A[sel][:, sel]
        nc, lab = csg.connected_components(sub, directed=False)
        idx = np.where(sel)[0]
        comp_area = np.bincount(lab, weights=area[idx])
        small = comp_area < (min_area if flag else min_area * 2)
        bad = idx[small[lab]]
        mask[bad] = not flag
    return mask


def trim_field(V, F, tooth_mask, bv_mask, offset, border_keepout=2.5, smooth_t=3.0, border_smooth_t=6.0, final_t=0.5, protect_mm=None):
    """Scalar g (mm): g<0 inside the kept region = within `offset` of the teeth (geodesic) and >= keepout from scan border.
    The offset field and the keep-out field are smoothed separately, then combined (smoothing the max() lets the
    border term leak across the scan edge)."""
    d_tooth = geodesic_from(V, F, tooth_mask)
    d_border = geodesic_from(V, F, bv_mask)
    g_off = d_tooth - offset
    if smooth_t > 0:
        g_off = smooth_scalar(V, F, g_off, smooth_t)
    db = smooth_scalar(V, F, d_border, border_smooth_t) if border_smooth_t > 0 else d_border
    db = np.maximum(db, 0.0)
    g = np.maximum(g_off, border_keepout - db)
    # make sure nothing on/near the raw border can end up inside
    g = np.where(d_border < 0.75 * border_keepout, np.maximum(g, 1e-3 + 0 * g), g)
    if final_t > 0:
        g2 = smooth_scalar(V, F, g, final_t)
        g = np.where(d_border < 0.75 * border_keepout, np.maximum(g2, 1e-3), g2)
    if protect_mm is not None and protect_mm >= 0:
        # tooth guarantee: crowns (+ a small margin ring) are ALWAYS kept, whatever smoothing / border keep-out say.
        # (cut_mesh treats |g|<0.01 as outside, so use a clearly negative value)
        g = np.where(d_tooth <= protect_mm, np.minimum(g, -0.05), g)
    return g, d_tooth, d_border


def cut_mesh(V, F, g):
    """Keep the part with g<0, inserting vertices on g=0 crossings. Returns (V2, F2, boundary_chain (ordered loops of vertex ids))."""
    g = np.where(np.abs(g) < 0.01, 0.01, g)     # avoid sliver triangles when the isoline grazes a vertex
    neg = g < 0
    nneg = neg[F].sum(1)
    keep_full = F[nneg == 3]
    mixed = F[(nneg == 1) | (nneg == 2)]
    newV = [V]; edge_id = {}; cnt = len(V)
    def cross(a, b):
        nonlocal cnt
        key = (a, b) if a < b else (b, a)
        v = edge_id.get(key)
        if v is None:
            ga, gb = g[a], g[b]
            t = ga / (ga - gb)
            newV.append((V[a] + (V[b] - V[a]) * t)[None, :])
            v = cnt; cnt += 1; edge_id[key] = v
        return v
    tris = [keep_full]
    out = []
    for f in mixed:
        s = neg[f]
        if s.sum() == 1:
            k = int(np.where(s)[0][0]); a, b, c = f[k], f[(k + 1) % 3], f[(k + 2) % 3]
            out.append([a, cross(a, b), cross(a, c)])
        else:
            k = int(np.where(~s)[0][0]); a, b, c = f[k], f[(k + 1) % 3], f[(k + 2) % 3]   # a is positive
            ab = cross(a, b); ac = cross(a, c)
            out.append([b, c, ac]); out.append([b, ac, ab])
    if out:
        tris.append(np.array(out, dtype=np.int64))
    F2 = np.vstack(tris)
    V2 = np.vstack(newV)
    # compact
    used = np.unique(F2); remap = -np.ones(len(V2), np.int64); remap[used] = np.arange(len(used))
    oid = np.where(used < len(V), used, -1)          # id in the ORIGINAL mesh, or -1 for vertices inserted on the cut
    V2 = V2[used]; F2 = remap[F2]
    return V2, F2, oid


def boundary_loops(F, V=None):
    """Ordered boundary loops (list of vertex id arrays), following face orientation."""
    he = np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]])
    s = set(map(tuple, he.tolist()))
    nxt = {}
    for a, b in s:
        if (b, a) not in s:
            nxt.setdefault(a, []).append(b)
    loops = []; used = set()
    for a in list(nxt):
        if a in used: continue
        loop = [a]; used.add(a); b = nxt[a][0]
        while b not in used:
            loop.append(b); used.add(b)
            if b not in nxt: break
            b = nxt[b][0]
        loops.append(np.array(loop))
    return loops


# ---------------------------------------------------------------- loop smoothing + base extrusion
from scipy.ndimage import gaussian_filter1d
from scipy.spatial import cKDTree


def main_loop(F):
    loops = boundary_loops(F)
    return max(loops, key=len), loops


def smooth_trim_loop(V, F, sigma=1.5, falloff=5.0, h=0.1, protect=None, xy_only=False):
    """Gaussian-smooth the trim loop along arc length (mm); extend the loop displacement into the surface as a
    harmonic field that is zero farther than `falloff` mm from the loop (damps jitter, avoids fold-overs).
    Returns the per-vertex displacement field D and the max loop displacement (mm)."""
    L, _ = main_loop(F)
    P = V[L]
    if sigma <= 0:                                  # no smoothing requested: zero displacement (was a ZeroDivisionError)
        return np.zeros_like(V), 0.0
    seg = np.linalg.norm(np.roll(P, -1, 0) - P, axis=1)
    s = np.concatenate([[0], np.cumsum(seg)])
    total = s[-1]
    m = int(round(total / h))
    su = np.linspace(0, total, m, endpoint=False)
    Pc = np.vstack([P, P[:1]])
    U = np.column_stack([np.interp(su, s, Pc[:, k]) for k in range(3)])
    Us = np.column_stack([gaussian_filter1d(U[:, k], sigma / h, mode='wrap') for k in range(3)])
    Usc = np.vstack([Us, Us[:1]]); suc = np.concatenate([su, [total]])
    Ls = np.column_stack([np.interp(s[:-1], suc, Usc[:, k]) for k in range(3)])
    delta = Ls - P
    if xy_only:                                   # keep every vertex at its own height: wall stays exactly vertical
        delta[:, 2] = 0.0
    n = len(V)
    dist, _ = cKDTree(P).query(V)
    fixed = np.zeros(n, bool); fixed[L] = True; fixed |= dist > falloff
    if protect is not None:                       # tooth zone: displacement is exactly 0 (pinned)
        fixed |= protect
        delta[protect[L]] = 0.0
    val = np.zeros((n, 3)); val[L] = delta
    # positive edge weights (1/length): robust on sliver triangles, tiny edges tie their endpoints together
    he = np.unique(np.sort(np.vstack([F[:, [0, 1]], F[:, [1, 2]], F[:, [2, 0]]]), axis=1), axis=0)
    el = np.linalg.norm(V[he[:, 0]] - V[he[:, 1]], axis=1)
    wgt = 1.0 / np.maximum(el, 0.005)
    W = sp.coo_matrix((wgt, (he[:, 0], he[:, 1])), shape=(n, n)); W = (W + W.T).tocsr()
    Lm = (sp.diags(np.asarray(W.sum(1)).ravel()) - W).tocsr()
    u = np.where(~fixed)[0]; b = np.where(fixed)[0]
    Luu = Lm[u][:, u].tocsc(); Lub = Lm[u][:, b]
    lu = splu(Luu)
    D = val.copy()
    for k in range(3):
        D[u, k] = lu.solve(-(Lub @ val[b, k]))
    D[L] = delta
    return D, np.linalg.norm(delta, axis=1).max()


def adaptive_strip_widths(shift, loop_len_step, strip, ratio=2.0, ref=0.25, floor=0.1, smooth_mm=1.5):
    """Per-loop-vertex fade width (mm). Where the smoothed trimline barely differs from the cut edge nothing needs to move,
    so the strip shrinks toward zero; where the edge shifts by `s` the strip is at least `ratio * s` wide (keeps the
    slope, and so the triangle squeeze, bounded) and at least `strip` once the shift reaches `ref` mm. The result is
    smoothed along the loop so the width varies gently."""
    from scipy.ndimage import gaussian_filter1d
    sm = gaussian_filter1d(shift, max(smooth_mm / max(loop_len_step, 1e-6), 1.0), mode='wrap')
    s = np.maximum(shift, sm)
    w = np.maximum(ratio * s, strip * np.minimum(1.0, s / ref))
    return np.maximum(w, floor)


def fade_trimline(V, F, sigma, strip, protect=None, zmove=True, h=0.1, adaptive=True):
    """Smooth the trim loop in 3D (outline AND height, Gaussian along arc length, `sigma` mm) and spread the resulting
    shift into the scan with a biharmonic fade that reaches exactly zero (with zero slope) at the strip's border, so
    it joins the untouched surface without a crease. The strip is `strip` mm wide where the edge shifts noticeably
    (never narrower than 2x the local shift) and narrows toward zero where it barely moves (`adaptive`).
    Crowns (`protect`) are pinned. Returns (displacement D, max edge shift)."""
    L, Ls = smoothed_loop_positions(V, F, sigma, h)
    if sigma <= 0:
        return np.zeros_like(V), 0.0
    P = V[L]
    delta = Ls - P
    if not zmove:
        delta[:, 2] = 0.0
    n = len(V)
    d, nn = cKDTree(P).query(V)
    if adaptive:
        step = float(np.linalg.norm(np.roll(P, -1, 0) - P, axis=1).mean())
        w = adaptive_strip_widths(np.linalg.norm(delta, axis=1), step, strip)
        fixed = np.zeros(n, bool); fixed[L] = True; fixed |= d > w[nn]
    else:
        fixed = np.zeros(n, bool); fixed[L] = True; fixed |= d > strip
    if protect is not None:
        fixed |= protect
        delta[protect[L]] = 0.0
    val = np.zeros((n, 3)); val[L] = delta
    b = np.where(fixed)[0]
    D = np.zeros((n, 3))
    D[:] = igl.harmonic(np.ascontiguousarray(V, dtype=np.float64), np.ascontiguousarray(F, dtype=np.int64),
                        b.astype(np.int64), np.ascontiguousarray(val[b]), 2)
    D[L] = delta
    if protect is not None:
        D[protect] = 0.0
    return D, float(np.linalg.norm(delta, axis=1).max())


def flipped_faces(V0, V1, F):
    def fn(V):
        n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-18)
    return int((np.einsum('ij,ij->i', fn(V0), fn(V1)) <= 0).sum())


def build_base(V, F, base_thickness=3.0, z_base=None, bottom_path=None):
    """Closed solid: scan patch + vertical wall below the trim loop + flat cap at z_base. Returns (V, F, info)."""
    import mapbox_earcut as earcut
    L, loops = main_loop(F)
    assert len(loops) == 1, f'expected 1 boundary loop, got {len(loops)}'
    top = V[L]
    # loop direction follows face orientation: patch lies on the left of the boundary half-edge
    if z_base is None:
        z_base = float(V[:, 2].min() - base_thickness)
    n = len(L)
    nv = len(V)
    if bottom_path is None:
        # vertical wall: bottom vertex directly below each trimline vertex
        bot = top.copy(); bot[:, 2] = z_base
        Vall = np.vstack([V, bot]); bidx = nv + np.arange(n)
        a = L; b = np.roll(L, -1); a2 = bidx; b2 = np.roll(bidx, -1)
        # boundary half-edge a->b exists in patch, wall must contain b->a
        wall = np.vstack([np.column_stack([b, a, a2]), np.column_stack([b, a2, b2])])
    else:
        # lofted wall: the bottom outline has its own (evenly spaced, smooth) vertices; wall strip is stitched between the
        # raw trimline (top) and the smooth outline (bottom) by plan-view arc length, so it cannot fold or twist.
        Q = np.asarray(bottom_path, float)
        m = len(Q)
        bot = np.column_stack([Q, np.full(m, z_base)])
        Vall = np.vstack([V, bot]); bidx = nv + np.arange(m)
        def param(P):
            sg = np.linalg.norm(np.roll(P, -1, 0) - P, axis=1); c = np.r_[0, np.cumsum(sg)]; return c / c[-1]
        t = param(top[:, :2]); u = param(Q)           # t[0]=u[0]=0 ... t[n]=u[m]=1 (closed)
        tris = []; i = j = 0
        while i < n or j < m:
            if i < n and (j >= m or t[i + 1] <= u[j + 1]):
                tris.append([L[(i + 1) % n], L[i], bidx[j % m]]); i += 1          # advance along the top edge a->b
            else:
                tris.append([L[i % n], bidx[j % m], bidx[(j + 1) % m]]); j += 1   # advance along the bottom edge c->d
        wall = np.array(tris)
    xy = Vall[nv:, :2].astype(np.float64)
    tri = earcut.triangulate_float64(xy, np.array([len(xy)], dtype=np.uint32)).reshape(-1, 3)
    cap = nv + tri
    p0, p1, p2 = xy[tri[:, 0]], xy[tri[:, 1]], xy[tri[:, 2]]
    area2 = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - (p2[:, 0] - p0[:, 0]) * (p1[:, 1] - p0[:, 1])
    cap = np.where((area2 > 0)[:, None], cap[:, ::-1], cap)
    Fall = np.vstack([F, wall, cap])
    info = dict(z_base=z_base, loop_len=n, wall_faces=len(wall), cap_faces=len(cap), patch_faces=len(F),
                cap_area=float(np.abs(area2).sum() / 2))
    return Vall, Fall, info


def fix_flipped(V0, V1, F, max_iter=60):
    """Relax vertices of triangles whose normal flipped relative to V0 (uniform Laplacian), loop vertices included
    only if needed. Returns repaired V1 and remaining flip count."""
    def fnorm(V):
        n = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-18)
    n0 = fnorm(V0)
    A = mesh_adjacency(V1, F)
    A.data[:] = 1.0
    deg = np.asarray(A.sum(1)).ravel()
    V = V1.copy()
    for it in range(max_iter):
        bad = np.einsum('ij,ij->i', n0, fnorm(V)) <= 1e-3
        if not bad.any():
            return V, 0
        vs = np.unique(F[bad])
        # also include one ring so the relaxation has room
        mask = np.zeros(len(V), bool); mask[vs] = True
        mask = mask | ((A @ mask.astype(float)) > 0)
        avg = (A @ V) / np.maximum(deg, 1)[:, None]
        V[mask] = 0.5 * V[mask] + 0.5 * avg[mask]
    bad = np.einsum('ij,ij->i', n0, fnorm(V)) <= 1e-3
    return V, int(bad.sum())


def safe_displace(V, F, D, max_iter=40):
    """V + alpha*D with per-vertex alpha in [0,1], backed off locally wherever a triangle would flip."""
    def fnorm(X):
        n = np.cross(X[F[:, 1]] - X[F[:, 0]], X[F[:, 2]] - X[F[:, 0]])
        return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-18)
    n0 = fnorm(V)
    A = mesh_adjacency(V, F); A.data[:] = 1.0
    alpha = np.ones(len(V))
    for it in range(max_iter):
        Vn = V + alpha[:, None] * D
        bad = np.einsum('ij,ij->i', n0, fnorm(Vn)) <= 0
        if not bad.any():
            return Vn, alpha, it
        m = np.zeros(len(V), bool); m[np.unique(F[bad])] = True
        m = m | ((A @ m.astype(float)) > 0)
        alpha[m] *= 0.5
    Vn = V + alpha[:, None] * D
    return Vn, alpha, max_iter


def smoothed_loop_positions(V, F, sigma, h=0.1):
    """Arc-length Gaussian smoothing of the boundary loop, evaluated at the loop's own vertices (no surface change).
    Returns (loop vertex ids, smoothed positions)."""
    L, _ = main_loop(F)
    P = V[L]
    if sigma <= 0:
        return L, P.copy()
    seg = np.linalg.norm(np.roll(P, -1, 0) - P, axis=1)
    s = np.concatenate([[0], np.cumsum(seg)]); total = s[-1]
    su = np.linspace(0, total, int(round(total / h)), endpoint=False)
    Pc = np.vstack([P, P[:1]])
    U = np.column_stack([np.interp(su, s, Pc[:, k]) for k in range(3)])
    Us = np.column_stack([gaussian_filter1d(U[:, k], sigma / h, mode='wrap') for k in range(3)])
    Usc = np.vstack([Us, Us[:1]]); suc = np.concatenate([su, [total]])
    return L, np.column_stack([np.interp(s[:-1], suc, Usc[:, k]) for k in range(3)])
