# VI Calculator
<img width="892" height="646" alt="image" src="https://github.com/user-attachments/assets/a16cdb4f-0876-4a12-9607-978eb1f4fc1e" />

A desktop tool for batch-computing vegetation indices (VIs) from multispectral and
RGB drone mosaics and extracting per-plot zonal statistics into a single Excel
workbook joined with field data.

**Developed by Ali Bazrafkan.**

---

## Table of contents
1. [What it does](#what-it-does)
2. [Required inputs](#required-inputs)
3. [Outputs](#outputs)
4. [Filename convention](#filename-convention)
5. [Vegetation indices](#vegetation-indices)
6. [Zonal statistics](#zonal-statistics)
7. [Installation](#installation)
8. [Running the app](#running-the-app)
9. [GUI walkthrough](#gui-walkthrough)
10. [Building a standalone `.exe`](#building-a-standalone-exe)
11. [Handling very large mosaics](#handling-very-large-mosaics)
12. [Project structure](#project-structure)
13. [Troubleshooting](#troubleshooting)
14. [Notes for collaborators](#notes-for-collaborators)

---

## What it does

Given a folder of geotiff mosaics, a shapefile of plot polygons, and an Excel
sheet of field measurements:

1. **Parses each raster filename** to recover (location, sensor, date, band).
2. **Groups rasters** by `(location, sensor, date)` — one group per flight.
3. **Streams** each plot's pixels off disk (no full-raster loads), reprojects
   the shapefile to the raster's CRS, computes vegetation indices on the fly,
   and aggregates statistics per `PlotID`.
4. Optionally writes user-selected VIs back to disk as tiled, compressed
   GeoTIFFs.
5. **Merges** the per-plot statistics with the user's field-data Excel by
   `PlotID` and produces a multi-sheet `.xlsx` output.

Memory use is bounded by the size of one plot's window and the tile size for
raster export, so the tool handles mosaics that are larger than RAM.

---

## Required inputs

| Input               | Format                  | Notes                                                       |
|---------------------|-------------------------|-------------------------------------------------------------|
| Raster folder       | folder of `*.tif`       | One file per MS band; optional `RGB` mosaic per date.        |
| Shapefile           | `*.shp` (+ sidecars)    | Plot polygons with a `PlotID` field.                         |
| Field data          | `*.xlsx`                | Sheet with a `PlotID` column matching the shapefile.         |
| Output folder       | folder                  | Created if missing.                                          |

The shapefile and Excel must share a column named **`PlotID`** (case
insensitive; `Plot`, `Plot_ID`, `plotid` also work). The shapefile is
automatically reprojected to each raster's CRS.

---

## Outputs

All outputs are written to your chosen output folder.

```
output/
├── VI_statistics.xlsx
└── VI_rasters/                  (only if "Save selected VIs" is enabled)
    ├── Irridrain_06262025_NDVI.tif
    ├── Irridrain_06262025_GNDVI.tif
    └── ...
```

`VI_statistics.xlsx` contains **five sheets**:

| Sheet         | Contents                                                      |
|---------------|---------------------------------------------------------------|
| `mean`        | Per-plot mean of each band/VI, by date.                       |
| `median`      | Per-plot median.                                              |
| `min`         | Per-plot minimum.                                             |
| `max`         | Per-plot maximum.                                             |
| `percentiles` | P10, P25, P50, P75, P90 for every band/VI.                    |

Every sheet starts with the columns from your field-data Excel (joined on
`PlotID`) and then has one column per `{date}_{band-or-VI}` (and additionally
`{date}_{band-or-VI}_P{n}` on the percentiles sheet).

---

## Filename convention

The parser expects multispectral band files in this form:

```
{Location}_MS_{MMDDYYYY}_transparent_reflectance_{band}.tif
```

Examples:

```
Irridrain_MS_06262025_transparent_reflectance_nir.tif
Irridrain_MS_06262025_transparent_reflectance_red edge.tif
Irridrain_MS_08112025_transparent_reflectance_green.tif
```

And RGB mosaics in this form:

```
{Location}_RGB_{MMDDYYYY}_transparent_mosaic_{anything}.tif
```

Example:

```
Irridrain_RGB_06262025_transparent_mosaic_group1.tif
```

Recognized band keywords (case insensitive): `blue`, `green`, `red`,
`red edge` / `rededge` / `red_edge`, `nir`.

Any file that doesn't match either pattern is silently skipped.

---

## Vegetation indices

The app computes every index whose required bands are present in a given group.

### MS-derived (require some combination of NIR / Red / Green / Red Edge)

| Name   | Formula                                           | Bands needed         |
|--------|---------------------------------------------------|----------------------|
| NDVI   | (NIR − Red) / (NIR + Red)                         | NIR, Red             |
| GNDVI  | (NIR − Green) / (NIR + Green)                     | NIR, Green           |
| NDRE   | (NIR − RE) / (NIR + RE)                           | NIR, Red Edge        |
| CIRE   | NIR / RE − 1                                      | NIR, Red Edge        |
| GCI    | NIR / Green − 1                                   | NIR, Green           |
| SAVI   | ((NIR − Red) · 1.5) / (NIR + Red + 0.5)           | NIR, Red             |
| OSAVI  | (NIR − Red) / (NIR + Red + 0.16) · 1.16           | NIR, Red             |
| MSAVI  | (2·NIR + 1 − √((2·NIR + 1)² − 8·(NIR − Red))) / 2 | NIR, Red             |
| NDREI  | (RE − Green) / (RE + Green)                       | Red Edge, Green      |
| MCARI  | ((RE − Red) − 0.2 · (RE − Green)) · (RE / Red)    | Red Edge, Red, Green |

### RGB-derived (require an RGB mosaic with bands R, G, B)

| Name    | Formula                                          |
|---------|--------------------------------------------------|
| VARI    | (G − R) / (G + R − B)                            |
| GLI     | (2G − R − B) / (2G + R + B)                      |
| NGRDI   | (G − R) / (G + R)                                |
| ExG     | 2G − R − B                                       |
| ExR     | 1.4R − G                                         |
| ExGR    | ExG − ExR                                        |
| TGI     | G − 0.39R − 0.61B                                |
| MGRVI   | (G² − R²) / (G² + R²)                            |
| RGBVI   | (G² − R·B) / (G² + R·B)                          |
| CIVE    | 0.441R − 0.811G + 0.385B + 18.78745              |

When zonal statistics are computed, you get:
- Stats per raw band (named `red`, `green`, `nir`, `rededge` for MS;
  `RGB_R`, `RGB_G`, `RGB_B` for RGB).
- Stats per VI (named with its index label, e.g. `NDVI`).

---

## Zonal statistics

For every plot polygon, the tool computes:

- `mean`
- `median`
- `min`
- `max`
- Percentiles: `P10`, `P25`, `P50`, `P75`, `P90`
- (`count` of valid pixels is also recorded internally; not exported.)

NaN / nodata pixels are excluded. Pixels with alpha == 0 in 4-band RGB mosaics
are treated as nodata.

---

## Installation

### Prerequisites

- Windows 10 or 11
- Python **3.10 or 3.11** on PATH
  (3.12+ is not recommended — some GIS wheels lag.)

### One-time setup

From the project folder:

```
setup_env.bat
```

This creates `.venv\` and installs the dependencies from `requirements.txt`:
`numpy`, `pandas`, `openpyxl`, `rasterio`, `geopandas`, `shapely`, `fiona`,
`pyproj`, `pyinstaller`.

If your machine sits behind a proxy that blocks pip, set the standard
`HTTPS_PROXY` / `HTTP_PROXY` environment variables before running.

---

## Running the app

```
run.bat
```

This activates `.venv\` and launches the GUI via `python app.py`. Use this
during development — there's no need to rebuild the `.exe` after every code
edit.

To run without the batch file:

```
.\.venv\Scripts\activate.bat
python app.py
```

---

## GUI walkthrough

The window has two panels:

- **Left panel — Log:** scrolling log of every step, plus a status line, a
  determinate progress bar, and a percentage indicator.
- **Right panel — Configuration:**
  - `Raster folder` — folder containing your `*.tif` files.
  - `Shapefile (.shp)` — path to the plot shapefile.
  - `Field data (.xlsx)` — path to the field-data Excel file.
  - `Output folder` — where outputs are written.
  - `Export VI rasters` group:
    - Master checkbox enables raster export.
    - Multi-select list of all 20 VIs (10 MS + 10 RGB). Use Ctrl/Shift-click,
      or the **Select all** / **Clear** buttons.
  - `Run` button starts the pipeline on a background thread so the UI stays
    responsive.

When the run finishes, a dialog confirms the output path.

---

## Building a standalone `.exe`

```
build.bat
```

This activates the venv, installs PyInstaller if missing, cleans previous
artifacts, and runs:

```
python -m PyInstaller --noconfirm viscalc.spec
```

The result is `dist\VIScalculator.exe` (single-file, `--windowed`, ~250-400 MB
because it bundles GDAL/rasterio/geopandas binaries and data files).

### Notes about distributing the .exe

On managed Windows machines (university / corporate), unsigned executables
trigger SmartScreen ("publisher not verified"). Options:

1. Run from source instead (`run.bat`) — no SmartScreen warning because
   `python.exe` is the executable and it's signed by the Python Software
   Foundation.
2. Ask IT to whitelist the SHA-256 of `dist\VIScalculator.exe`.
3. Code-sign with Microsoft Trusted Signing or a Sectigo/DigiCert OV cert.

---

## Handling very large mosaics

The pipeline never loads a full band into RAM:

- Each raster file is opened as a `rasterio` handle. If a band is not on the
  reference grid, it's wrapped in a `WarpedVRT` so windowed reads come back
  aligned without materializing the whole image.
- For every plot, only the pixel window enclosing that plot is read from disk,
  the polygon mask is rasterized at that small size, and stats are computed.
- VI raster export walks the mosaic in `tile × tile` chunks (default 1024 px)
  and writes one tile per VI per step. Peak memory ≈ `tile² × n_bands × 4` bytes.

Tips for very large mosaics:

- **Make sure inputs are tiled, not stripped.** Drone software outputs almost
  always are, but if needed:
  ```
  gdal_translate -co TILED=YES -co COMPRESS=LZW -co BIGTIFF=IF_SAFER in.tif out.tif
  ```
- **Keep mosaics on a local SSD.** Network shares are dramatically slower for
  windowed reads.
- **Skip VI raster export if you don't need it** — only the export pass touches
  every pixel; the stats pass touches only pixels inside plot polygons.
- **Raise `tile_size` in `viscalc/pipeline.py`** (default 1024) to 2048 or 4096
  if you have RAM and want fewer I/O round-trips.

---

## Project structure

```
VIScalculator3/
├── app.py                      Entry point used by PyInstaller and run.bat
├── viscalc.spec                PyInstaller configuration
├── build.bat                   Build VIScalculator.exe
├── run.bat                     Launch from source via .venv
├── setup_env.bat               Create .venv and install requirements
├── requirements.txt            Python dependencies
├── README.md                   This file
└── viscalc/
    ├── __init__.py
    ├── __main__.py             Allows: python -m viscalc
    ├── gui.py                  Tkinter two-panel GUI
    ├── pipeline.py             Streaming orchestrator: groups, zonal pass, tiled VI writer
    ├── parser.py               Filename → (location, sensor, date, band)
    ├── indices.py              MS and RGB vegetation index formulas + ALL_VI_NAMES list
    ├── zonal.py                Per-plot windowed zonal statistics
    └── excel.py                Pivot long-form stats into the 5-sheet workbook
```

---

## Troubleshooting

**The Run button does nothing / status stays at "Idle"**
Check the **Log** panel — any validation error is printed there, and an error
dialog usually pops up. The most common cause is a missing input or a
shapefile/Excel with no recognizable `PlotID` column.

**"No recognized rasters found"**
None of the `.tif` filenames match the expected pattern. Confirm names follow
the convention above. Files in subfolders are not scanned.

**"Could not find a PlotID column"**
Rename the relevant column in your shapefile or Excel to `PlotID`.

**Zonal stats are all NaN**
The plot polygons probably don't overlap the raster footprint, or the
shapefile CRS metadata is missing. Open the shapefile and the raster in QGIS to
confirm they line up.

**Run takes forever and the progress bar barely moves**
The raster is likely stripped instead of tiled, forcing slow strip
re-decompression on each windowed read. Re-encode the mosaic with
`gdal_translate -co TILED=YES`.

**PyInstaller build error: missing `proj.db` / `gcs.csv`**
The spec uses `collect_all` for `pyproj`, `rasterio`, `fiona`, `geopandas`,
which usually handles it. If you still hit it, run inside the venv:
```
python -m pip install --force-reinstall rasterio pyproj fiona
build.bat
```

**The built `.exe` won't launch on another machine**
First try running it from a terminal so you can see the traceback:
```
dist\VIScalculator.exe
```
The most common cause is missing Visual C++ Redistributable for VS 2015-2022.

**SmartScreen blocks the `.exe`**
See "Notes about distributing the .exe" above. Easiest workaround is to ship
the source folder and run via `run.bat`.

---

## Notes for collaborators

- Add new vegetation indices in `viscalc/indices.py` (either `compute_indices`
  for MS or `compute_rgb_indices` for RGB) **and** append the new VI name to
  `ALL_VI_NAMES` so it shows up in the GUI listbox.
- Add new statistics in `viscalc/zonal.py:_stats_for_pixels` and surface them
  via `viscalc/excel.py`.
- The Excel layout is `{date}_{layer}` per column. If you flight multiple
  locations into the same output folder, layers from different locations land
  on the same sheet — `location` is included in the long-form intermediate
  but dropped during pivot. Modify `viscalc/excel.py` to include `location` in
  the column key if you need that distinction.

---

**Developed by Ali Bazrafkan.**
