#!/usr/bin/env python3
"""Raw intraoral scan STL -> watertight, flat-base horseshoe dental model STL (geometry only, no ML).

Examples:
  python make_base.py scan_upper.stl out_upper.stl
  python make_base.py scan_lower.stl out_lower.stl --offset 3 --preview
  python make_base.py scans/*.stl --outdir out --offset 2 4 6      # batch, several offsets
"""
import argparse, json, os, sys, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dentalbase.pipeline import make_base


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('inputs', nargs='+', help='input STL (then output STL), or several input STLs with --outdir')
    ap.add_argument('--outdir', help='batch mode: write <name>_base_o<offset>.stl here')
    ap.add_argument('--offset', type=float, nargs='+', default=[4.0], help='gingiva margin height in mm (geodesic offset from crowns); several values = several outputs (default 4)')
    ap.add_argument('--smooth', type=float, default=6.0, help='trimline field smoothing (default 6)')
    ap.add_argument('--loop-sigma', type=float, default=1.5, help='trimline arc-length smoothing in mm (default 1.5)')
    ap.add_argument('--thickness', type=float, default=3.0, help='base thickness below the lowest scan point in mm (default 3)')
    ap.add_argument('--preview', action='store_true', help='also write a PNG render next to each output')
    a = ap.parse_args()

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
