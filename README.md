# dental-base-model

Raw intraoral scan (STL, one arch) -> watertight, flat-base, horseshoe-style dental model (STL).
Pure geometry processing, **no machine learning, no GPU, no model weights**.

## What it does
1. Cleans the scan (merge duplicate vertices, drop tiny fragments).
2. Estimates the occlusal plane / up-direction from the cusps and re-orients the mesh.
3. Finds the crown vs. gingiva region without a trained segmenter: a random-walker field over the mesh whose
   edge weights are cut at concave creases (curvature barriers), seeded by cusp tips (crown) and the scan border (gum).
4. Builds a trimline at a geodesic offset from the crowns (`--offset`, the "gingiva margin height"), smooths the
   trim field and then the trim loop itself, and cuts the scan there. If the kept region splits (gaps, small offsets)
   it bridges the pieces so the base stays one continuous horseshoe.
5. Extrudes the loop as a vertical wall down to a flat plane `--thickness` mm below the lowest scan point and caps it.

## Setup (Python 3.10+, developed/tested on 3.13)
```bash
python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
All dependencies install from PyPI as prebuilt wheels (numpy, scipy, trimesh, libigl, potpourri3d, manifold3d,
mapbox-earcut, networkx, matplotlib, pillow). No compiler needed on common platforms. If `pip install libigl` or
`potpourri3d` finds no wheel for your Python/OS, try Python 3.11-3.13.

## Run
```bash
# one scan -> one model
python make_base.py upper_scan.stl upper_base.stl

# change margin height, add a PNG preview
python make_base.py lower_scan.stl lower_base.stl --offset 3 --preview

# batch: many scans x several offsets -> out/<name>_base_o<offset>.stl
python make_base.py scans/*.stl --outdir out --offset 2 4 6

# independent printability check of any exported STL
python verify.py upper_base.stl
```
Typical run: ~15-20 s per scan (200-270k triangles) on a 2-core CPU, a few GB RAM.

| option | default | meaning |
|---|---|---|
| `--offset` | 4.0 | gingiva margin height in mm: geodesic distance from the crowns to the trimline (several values allowed) |
| `--smooth` | 6.0 | smoothing of the trim field before the cut (higher = rounder, less hugging of the gum line) |
| `--loop-sigma` | 1.5 | arc-length smoothing of the final trim loop in mm |
| `--thickness` | 3.0 | base thickness below the lowest scan point in mm |
| `--preview` | off | write a PNG render next to each output |

Units are the STL's units; scans are assumed to be in **millimetres**.

## Reading the result
`make_base.py` prints a JSON report. `watertight: true` and `euler: 2` mean a simple closed solid.
`verify.py` additionally reports genus (0 = no tunnels) and checks the mesh with a second kernel (manifold3d).

## Known limitations (be aware before relying on it)
- **Input must be a single-arch scan with one open border** (the usual cropped intraoral scan). A closed/watertight input
  has no border to seed the gum from and will fail.
- **Handles/tunnels already present in the raw scan are not removed.** In the test set the lower scan has genus 3;
  trimming removed one and the output kept two tunnels (output `euler: -2`). The CLI prints a warning when `euler != 2`.
  Planned fix: detect and cap handles before building the base.
- The lower test scan at `--offset 2` produced a non-manifold result (cause not yet found). Offsets 4 and 6 were watertight.
- Self-intersection checking is not part of `verify.py`; a manifold solid is not proof of no self-intersections.
  Open the result in your slicer and run its repair/check as well.
- Tested on only two scans (one upper, one lower). Crowding, braces, missing teeth, restorations are untested.
  Margin accuracy has not been measured against labelled ground truth; judge the preview before printing.
- The flat base sits below the lowest scan point, so arches with tall posterior ends get tall posterior blocks.

## Layout
```
make_base.py          command-line tool
verify.py             printability checks
dentalbase/pipeline.py   end-to-end make_base() + crown segmentation + island bridging
dentalbase/dbase.py      geometry primitives (curvature, random walker, geodesics, cut, loop smoothing, base build)
dentalbase/render.py     preview rendering (matplotlib)
```
Use from Python: `from dentalbase.pipeline import make_base; make_base('in.stl', 'out.stl', offset=4.0)`
