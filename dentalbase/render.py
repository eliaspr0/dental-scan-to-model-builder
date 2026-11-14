import numpy as np, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import PolyCollection

def shade_faces(V, F, light=(0.3, 0.3, 1.0)):
    l = np.array(light, float); l /= np.linalg.norm(l)
    fn = np.cross(V[F[:,1]]-V[F[:,0]], V[F[:,2]]-V[F[:,0]])
    fn /= np.maximum(np.linalg.norm(fn,axis=1,keepdims=True),1e-12)
    return fn, np.clip(fn@l, 0, 1)

def render_top(V, F, out, vcolor=None, curves=(), title='', view='top', size=9, cmap='RdBu_r', vmin=None, vmax=None, lines_colors=None, dpi=130):
    """Orthographic render. view: top (x,y; depth z) or side (x,z; depth y)."""
    if view == 'top': ax_i, ax_j, ax_d = 0, 1, 2
    elif view == 'side': ax_i, ax_j, ax_d = 0, 2, 1
    elif view == 'front': ax_i, ax_j, ax_d = 1, 2, 0
    P = V[:, [ax_i, ax_j]]
    fn, sh = shade_faces(V, F, light=[0.25,0.25,1.0] if view=='top' else [0.25,1.0,0.35])
    depth = V[F][:,:,ax_d].mean(1)
    # backface cull for top: keep faces whose normal points to viewer (+z for top)
    facing = fn[:, ax_d] > -0.2 if view=='top' else np.ones(len(F), bool)
    order = np.argsort(depth)  # painter's: far first
    order = order[facing[order]]
    if vcolor is not None:
        cm = plt.get_cmap(cmap)
        vmin = np.percentile(vcolor,2) if vmin is None else vmin
        vmax = np.percentile(vcolor,98) if vmax is None else vmax
        fc = vcolor[F].mean(1)
        col = cm((fc - vmin)/(vmax-vmin+1e-12))[:, :3]
        col = col * (0.55 + 0.45*sh[:,None])
    else:
        col = np.column_stack([sh*0.85+0.1]*3)*np.array([1.0,0.95,0.88])
    fig, ax = plt.subplots(figsize=(size, size*(np.ptp(P[:,1])+4)/(np.ptp(P[:,0])+4)), dpi=dpi)
    pc = PolyCollection(P[F[order]], facecolors=np.clip(col[order],0,1), edgecolors='none', antialiaseds=False)
    ax.add_collection(pc)
    for k, c in enumerate(curves):
        c = np.asarray(c)
        colr = (lines_colors[k] if lines_colors else 'lime')
        ax.plot(c[:, ax_i], c[:, ax_j], '-', color=colr, lw=1.6)
    ax.set_xlim(P[:,0].min()-2, P[:,0].max()+2); ax.set_ylim(P[:,1].min()-2, P[:,1].max()+2)
    ax.set_aspect('equal'); ax.axis('off'); ax.set_title(title, fontsize=10)
    fig.tight_layout(pad=0.3); fig.savefig(out); plt.close(fig)


def view_matrix(azim, elev):
    """Rotation so that a camera at (azim, elev) deg looks at origin; returns R with rows (right, up, toward-viewer)."""
    a, e = np.radians(azim), np.radians(elev)
    toward = np.array([np.cos(e)*np.sin(a), -np.cos(e)*np.cos(a), np.sin(e)])
    up0 = np.array([0, 0, 1.0])
    right = np.cross(up0, toward); right /= np.linalg.norm(right)
    up = np.cross(toward, right)
    return np.vstack([right, up, toward])


def render_view(V, F, out, azim=0, elev=30, vcolor=None, curves=(), lines_colors=None, title='', size=9,
                cmap='RdBu_r', vmin=None, vmax=None, dpi=120, center=None, zoom=None, lw=1.6, base_color=(1.0,0.95,0.88)):
    R = view_matrix(azim, elev)
    c = V.mean(0) if center is None else np.asarray(center)
    Vr = (V - c) @ R.T
    fn = np.cross(Vr[F[:,1]]-Vr[F[:,0]], Vr[F[:,2]]-Vr[F[:,0]])
    fn /= np.maximum(np.linalg.norm(fn,axis=1,keepdims=True),1e-12)
    l = np.array([0.3,0.4,1.0]); l/=np.linalg.norm(l)
    sh = np.clip(fn@l,0,1)
    depth = Vr[F][:,:,2].mean(1)
    facing = fn[:,2] > -0.05
    order = np.argsort(depth); order = order[facing[order]]
    if vcolor is not None:
        cm = plt.get_cmap(cmap)
        vmin = np.percentile(vcolor,2) if vmin is None else vmin
        vmax = np.percentile(vcolor,98) if vmax is None else vmax
        col = cm((vcolor[F].mean(1)-vmin)/(vmax-vmin+1e-12))[:,:3]*(0.55+0.45*sh[:,None])
    else:
        col = np.column_stack([sh*0.85+0.1]*3)*np.array(base_color)
    P = Vr[:, :2]
    if zoom is None:
        xl = (P[:,0].min()-2, P[:,0].max()+2); yl=(P[:,1].min()-2, P[:,1].max()+2)
    else:
        xl, yl = zoom
    fig, ax = plt.subplots(figsize=(size, size*(yl[1]-yl[0])/(xl[1]-xl[0])), dpi=dpi)
    ax.add_collection(PolyCollection(P[F[order]], facecolors=np.clip(col[order],0,1), edgecolors='none', antialiaseds=False))
    for k, cv in enumerate(curves):
        cv = (np.asarray(cv) - c) @ R.T
        # hide curve parts that face away (simple: draw all, then rely on depth? keep all)
        ax.plot(cv[:,0], cv[:,1], '-', color=(lines_colors[k] if lines_colors else 'lime'), lw=lw)
    ax.set_xlim(*xl); ax.set_ylim(*yl); ax.set_aspect('equal'); ax.axis('off'); ax.set_title(title, fontsize=10)
    fig.tight_layout(pad=0.3); fig.savefig(out); plt.close(fig)
