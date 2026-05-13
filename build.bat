@echo off
REM Build VIScalculator.exe with PyInstaller.
REM Run this from a Python venv that has the project requirements installed.

set NAME=VIScalculator

REM Clean previous artifacts
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
if exist %NAME%.spec del /q %NAME%.spec

pyinstaller ^
    --name %NAME% ^
    --onefile ^
    --windowed ^
    --collect-all rasterio ^
    --collect-all fiona ^
    --collect-all geopandas ^
    --collect-all pyproj ^
    --collect-all shapely ^
    --collect-submodules rasterio ^
    --collect-submodules fiona ^
    --hidden-import rasterio._shim ^
    --hidden-import rasterio.vrt ^
    --hidden-import rasterio.sample ^
    --hidden-import rasterio.control ^
    --hidden-import fiona._shim ^
    --hidden-import fiona.schema ^
    app.py

echo.
echo Build done. Executable: dist\%NAME%.exe
