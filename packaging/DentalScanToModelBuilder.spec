# PyInstaller spec: pyinstaller packaging/DentalScanToModelBuilder.spec --noconfirm
import sys, os
from PyInstaller.utils.hooks import collect_all, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, '..'))
datas, binaries, hidden = [], [], []
for pkg in ('igl', 'potpourri3d', 'manifold3d', 'mapbox_earcut', 'triangle', 'trimesh', 'scipy', 'networkx'):
    try:
        d, b, h = collect_all(pkg)
        datas += d; binaries += b; hidden += h
    except Exception as e:
        print('collect_all skipped', pkg, e)
hidden += collect_submodules('dentalbase') + collect_submodules('dentalbase_gui') + ['make_base']

icon = os.path.join(SPECPATH, 'icon.icns' if sys.platform == 'darwin' else 'icon.ico')
excludes = ['tkinter', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.Qt3DCore', 'PySide6.QtQuick',
            'PySide6.QtQml', 'PySide6.QtMultimedia', 'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtPdf',
            'PySide6.QtSql', 'PySide6.QtTest', 'IPython', 'pytest', 'sphinx']

a = Analysis([os.path.join(ROOT, 'gui.py')], pathex=[ROOT], datas=datas, binaries=binaries, hiddenimports=hidden,
             excludes=excludes, noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='DentalScanToModelBuilder', console=False,
          icon=icon if os.path.exists(icon) else None, upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name='DentalScanToModelBuilder', upx=False)
if sys.platform == 'darwin':
    app = BUNDLE(coll, name='Dental Scan to Model Builder.app', icon=icon if os.path.exists(icon) else None,
                 bundle_identifier='org.dentalscan.modelbuilder',
                 info_plist={'NSHighResolutionCapable': True, 'CFBundleShortVersionString': '1.0.0'})
