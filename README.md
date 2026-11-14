# dental-base-model  (v0.2)

Raw intraoral scan (STL, one arch) -> watertight, flat-base, horseshoe-style dental model (STL).
Pure geometry processing, **no machine learning, no GPU, no model weights**.

## Guarantees (v0.2) - checked automatically after every export
- **Articulation is preserved.** The output STL is written in the *input scan's own coordinate system*. An upper and
  a lower scan that were bite-registered in one frame stay in occlusion when loaded together (checked: minimum
  upper-lower gap identical before/after). Use `--pair` so both bases are also parallel to the shared bite plane.
- **Tooth geometry is not altered.** Crown vertices plus a small margin ring are copied bit-for-bit from the input:
  never smoothed, moved, remeshed or cut away. The report prints `crown_exact_pct` (should be 100.0) and
  `crown_max_dev_mm` (should be 0.0), measured by reloading the exported STL and comparing with the input.
  (v0.1 did NOT guarantee this: its loop smoothing displaced 19-60% of crown vertices by up to ~0.6 mm.)
- The scan surface is cut at the trimline and nothing else is changed except a ~1 mm strip along that cut edge (tiny
  de-jitter, max ~0.3 mm shift, fading to zero); everything farther from the edge is bit-exact. Plus the added wall and base.

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

# articulated pair (recommended for upper+lower): shared bite plane, original coordinates kept
python make_base.py --pair upper_scan.stl lower_scan.stl --outdir out --offset 4

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
| `--offset` | 4.5 | gingiva margin height in mm: geodesic distance from the crowns to the trimline (several values allowed) |
| `--smooth` | 6.0 | advanced: smoothing of the trim field before the cut. Barely changes the wall; not shown in the GUI |
| `--loop-sigma` | 1.5 | trimline smoothing in mm: shapes the wall/base outline. The cut edge itself is also de-jittered (sigma 0.75 mm, fading out within 1 mm of the edge) so the wall has no ripples |
| `--thickness` | 0.5 | base thickness below the lowest scan point in mm |
| `--trim-mode` | base | `base`: only a ~1 mm strip along the cut edge is de-jittered, the rest of the scan is untouched (default). `deform`: legacy, also blends the smoothing into the surface within ~5 mm of the trimline |
| `--preview` | off | write a PNG render next to each output |

Units are the STL's units; scans are assumed to be in **millimetres**.

## Desktop GUI (drag & drop)
```bash
pip install -r requirements-gui.txt     # PySide6; the backend requirements must be installed in the same environment
python gui.py
```
Drop binary `.stl` scans onto the left area (or *Add files...*), set each file's arch (Upper / Lower / Single arch; guessed from
the file name), tune the options on the right and press **Generate**. Outputs are written next to each input as
`<name>_output.stl` (binary STL). Only binary STL is accepted as input (ASCII STL is rejected); outputs are binary STL.
With exactly one Upper and one Lower file the *Articulated pair* option makes both bases parallel to the shared bite plane.
Each row shows its result, including a warning when the mesh is not a simple closed solid.

The GUI (`dentalbase_gui/`) is fully decoupled from the backend: it never imports `dentalbase`; it runs `make_base.py` as a
subprocess (so it can be cancelled) and reads its output. Backend and GUI can change independently as long as the
`make_base.py` command line stays the same. Logic tests (no display needed): `python -m unittest tests.test_gui_logic`.

## Reading the result
`make_base.py` prints a JSON report. `watertight: true` and `euler: 2` mean a simple closed solid.
`verify.py` additionally reports genus (0 = no tunnels) and checks the mesh with a second kernel (manifold3d).

## Known limitations (be aware before relying on it)
- **Local wall self-intersections near the ragged distal ends of a scan (found with the MeshLab check).** On the
  lower test scan the exported solid has ~270-320 self-intersecting faces (clusters at the posterior ends, where the
  vertical wall passes through other geometry); on the upper ~15 tiny ones. The raw scans have 6 and 0. Tooth surfaces are
  unaffected, but the base wall there needs repair (slicer repair / future fix) before printing.
- **Lower scan, offset 4, default settings: the exported mesh is not watertight** in v0.2 (cap triangulation of a
  self-crossing trimline polygon). Offset 4 with `--loop-sigma 3` gave a watertight but still self-intersecting result.
  The CLI prints a warning whenever `euler != 2`.
- **Handles/tunnels already present in the raw scan are not removed** (the lower test scan has genus 3).
- Lower scan at `--offset 2` was non-manifold in v0.1; not re-fixed.
- **Input must be a single-arch scan with one open border** (usual cropped intraoral scan).
- Tested on only two scans; margin accuracy not measured against labelled ground truth. Check every preview.
- The flat base sits below the lowest scan point, so arches with tall posterior ends get tall posterior blocks.
- Optional self-intersection check: `pip install pymeshlab` (Linux also needs `apt install libopengl0`); `verify.py` uses it if present.

## Layout
```
make_base.py          command-line tool
verify.py             printability checks
dentalbase/pipeline.py   end-to-end make_base() + crown segmentation + island bridging
dentalbase/dbase.py      geometry primitives (curvature, random walker, geodesics, cut, loop smoothing, base build)
dentalbase/render.py     preview rendering (matplotlib)
gui.py, dentalbase_gui/  desktop GUI (PySide6), talks to the backend only through make_base.py
tests/                   GUI logic tests
```
Use from Python: `from dentalbase.pipeline import make_base; make_base('in.stl', 'out.stl', offset=4.0)`
