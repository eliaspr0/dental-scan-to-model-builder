#!/usr/bin/env python3
"""Raw intraoral scan STL -> watertight, flat-base horseshoe dental model STL (geometry only, no ML).

Examples:
  python make_base.py scan_upper.stl out_upper.stl
  python make_base.py scan_lower.stl out_lower.stl --offset 3 --preview
  python make_base.py scans/*.stl --outdir out --offset 2 4 6      # batch, several offsets
  python make_base.py --pair upper.stl lower.stl --outdir out        # articulated pair: shared bite plane, original coordinates
"""
import argparse, json, os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dentalbase.pipeline import make_base, make_pair


def _utf8_streams():
    """File names may contain non-ASCII letters (e.g. Greek). On Windows a piped stdout defaults to a legacy codepage (cp1252)
    that cannot print them, which used to crash the run; always write UTF-8 (the GUI reads it as UTF-8)."""
    for st in (sys.stdout, sys.stderr):
        try:
            st.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass


def main():
    _utf8_streams()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inputs', nargs='*', help='input STL (then output STL), or several input STLs with --outdir')
    ap.add_argument('--outdir', help='batch mode: write <name>_base_o<offset>.stl here')
    ap.add_argument('--offset', type=float, nargs='+', default=[4.5], help='gingiva margin height in mm (geodesic offset from crowns); several values = several outputs (default 4.5)')
    ap.add_argument('--smooth', type=float, default=6.0, help='trimline field smoothing (default 6)')
    ap.add_argument('--loop-sigma', type=float, default=1.5, help='smoothing of the base outline below the trimline, in mm (default 1.5); the scan surface is never modified in the default --trim-mode base')
    ap.add_argument('--thickness', type=float, default=0.5, help='base thickness below the lowest scan point in mm (default 0.5)')
    ap.add_argument('--trim-mode', choices=['base', 'deform'], default='base', help="base (default): scan surface untouched, only the base outline is smoothed; deform: legacy, also blends the smoothing into the surface within ~5 mm of the trimline")
    ap.add_argument('--strip', type=float, default=None, help='advanced: width in mm of the strip along the cut edge where the scan follows the smoothed trimline (default: automatic: 1 mm where the edge moves noticeably, narrower where it barely moves, wider only if needed)')
    ap.add_argument('--preview', action='store_true', help='also write a PNG render next to each output')
    ap.add_argument('--pair', nargs=2, metavar=('UPPER', 'LOWER'), help='articulated pair: both bases parallel to the shared bite plane; outputs stay in the scans\' original (bite-registered) coordinates')
    ap.add_argument('--pair-out', nargs=2, metavar=('UPPER_OUT', 'LOWER_OUT'), help='with --pair: explicit output paths (instead of --outdir); needs a single --offset')
    a = ap.parse_args()

    if a.pair:
        if not a.outdir and not a.pair_out:
            ap.error('--pair needs --outdir or --pair-out')
        if a.pair_out and len(a.offset) != 1:
            ap.error('--pair-out needs exactly one --offset')
        if a.outdir:
            os.makedirs(a.outdir, exist_ok=True)
        for off in a.offset:
            up, lo = a.pair
            if a.pair_out:
                uo, lo_o = a.pair_out
            else:
                uo = os.path.join(a.outdir, f"{os.path.splitext(os.path.basename(up))[0]}_base_o{off:g}.stl")
                lo_o = os.path.join(a.outdir, f"{os.path.splitext(os.path.basename(lo))[0]}_base_o{off:g}.stl")
            print(f'\n=== pair (offset {off:g} mm): {up} + {lo}')
            reps = make_pair(up, lo, uo, lo_o, offset=off, smooth_t=a.smooth, loop_sigma=a.loop_sigma, base_thickness=a.thickness, trim_mode=a.trim_mode, strip=a.strip)
            for r, dst in zip(reps, (uo, lo_o)):
                print(os.path.basename(dst), json.dumps({k: r[k] for k in ('watertight', 'euler', 'crown_exact_pct', 'crown_max_dev_mm', 'crown_area_kept_pct')}))
                if not r['watertight'] or r['euler'] != 2:
                    print('  WARNING: not a simple closed solid (watertight=%s, euler=%s). Run verify.py.' % (r['watertight'], r['euler']))
        return
    if not a.inputs:
        ap.error('give INPUT.stl OUTPUT.stl, or several STLs with --outdir, or --pair UPPER LOWER --outdir DIR')

    if a.outdir:
        os.makedirs(a.outdir, exist_ok=True)
        jobs = []
        for pat in a.inputs:
            for f in (glob.glob(pat) or [pat]):
                for o in a.offset:
                    jobs.append((f, os.path.join(a.outdir, f"{os.path.splitext(os.path.basename(f))[0]}_base_o{o:g}.stl"), o))
    else:
        if len(a.inputs) != 2 or len(a.offset) != 1:
            ap.error('single mode needs exactly: INPUT.stl OUTPUT.stl and one --offset (use --outdir for batch)')
        jobs = [(a.inputs[0], a.inputs[1], a.offset[0])]

    for src, dst, off in jobs:
        print(f'\n=== {src} -> {dst} (offset {off:g} mm)')
        rep = make_base(src, dst, off, a.smooth, a.loop_sigma, a.thickness)
        print(json.dumps(rep))
        if not rep['watertight'] or rep['euler'] != 2:
            print('  WARNING: not a simple closed solid (watertight=%s, euler=%s). Euler != 2 means handles/tunnels, usually already in the raw scan. Run verify.py.' % (rep['watertight'], rep['euler']))
        if a.preview:
            import numpy as np, trimesh
            from dentalbase import render
            m = trimesh.load(dst, process=True)
            render.render_view(np.asarray(m.vertices), np.asarray(m.faces), os.path.splitext(dst)[0] + '.png', azim=15, elev=42, title=os.path.basename(dst), size=8, dpi=110)


if __name__ == '__main__':
    main()
