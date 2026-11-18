# Third-party software

This application is built on the open-source libraries below. Each keeps its own licence; none of them is changed by this
repository's licence. Licences were read from the installed packages.

| Library | Licence | Notes |
|---|---|---|
| PySide6 (Qt for Python) | LGPL-3.0 / GPL | Used unmodified and dynamically linked; you may replace the Qt libraries in the packaged app |
| numpy, scipy, networkx | BSD-3-Clause | |
| trimesh, potpourri3d | MIT | |
| mapbox-earcut | ISC | |
| manifold3d | Apache-2.0 | |
| Pillow | MIT-CMU | |
| matplotlib | PSF-style | |
| libigl (Python bindings) | MPL-2.0 | Used unmodified |
| **triangle** | LGPL-3.0 (Python wrapper) | **Bundles Jonathan Shewchuk's Triangle, which restricts commercial use.** Fine for noncommercial use; replace it before any commercial distribution. |
| PyInstaller (build tool only) | GPL-2.0+ with bundling exception | The exception means packaged apps are not GPL |

Please check each project's own licence text for the exact terms.
