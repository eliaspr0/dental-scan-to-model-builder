#!/usr/bin/env python3
"""Launch the desktop GUI:  python gui.py   (needs: pip install -r requirements-gui.txt)

The packaged app (PyInstaller) has no separate Python, so it runs the backend by starting itself with
`--run-backend <make_base.py arguments>`; `--selftest` checks that every dependency loads."""
import sys


def _selftest():
    import numpy, scipy, trimesh, igl, manifold3d, mapbox_earcut, networkx, potpourri3d, PySide6  # noqa: F401
    import dentalbase.pipeline  # noqa: F401
    print('selftest ok')


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    if len(sys.argv) > 1 and sys.argv[1] == '--run-backend':
        sys.argv = ['make_base.py'] + sys.argv[2:]
        import os
        for name in ('stdout', 'stderr'):   # windowed Windows builds may start without console streams
            if getattr(sys, name) is None:
                setattr(sys, name, open(os.devnull, 'w'))
        import make_base
        make_base.main()
    elif len(sys.argv) > 1 and sys.argv[1] == '--selftest':
        _selftest()
    else:
        from dentalbase_gui.app import main
        main()
