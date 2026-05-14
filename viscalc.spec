# PyInstaller spec for VIScalculator
# Build with:  python -m PyInstaller --noconfirm viscalc.spec
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []

for pkg in ("rasterio", "fiona", "geopandas", "pyproj", "shapely", "openpyxl"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

hiddenimports += [
    "rasterio._shim",
    "rasterio.vrt",
    "rasterio.sample",
    "rasterio.control",
    "rasterio._features",
    "rasterio._io",
    "rasterio._warp",
    "fiona._shim",
    "fiona.schema",
]

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="VIScalculator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
)
