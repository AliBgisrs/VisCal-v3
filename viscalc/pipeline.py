"""Main processing pipeline: scan rasters, compute VIs, run zonal stats, build long table."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.warp import Resampling, reproject

from .indices import compute_indices
from .parser import RasterFile, scan_folder
from .zonal import PERCENTILES, extract_stats_from_array

log = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    raster_folder: Path
    shapefile: Path
    field_excel: Path
    output_folder: Path
    plot_id_col: Optional[str] = None  # auto-detect if None
    save_vi_rasters: bool = False
    progress: Optional[Callable[[str], None]] = None


def _log(cfg: PipelineConfig, msg: str) -> None:
    log.info(msg)
    if cfg.progress is not None:
        cfg.progress(msg)


def _detect_plot_id_column(df: pd.DataFrame, hint: Optional[str]) -> str:
    if hint and hint in df.columns:
        return hint
    candidates = [c for c in df.columns if str(c).lower().replace("_", "") in ("plotid", "plot")]
    if candidates:
        return candidates[0]
    raise ValueError(
        f"Could not find a PlotID column in {list(df.columns)}. "
        "Rename the column to 'PlotID' or pass plot_id_col explicitly."
    )


def _load_band_array(rf: RasterFile, ref_path: Path) -> tuple[np.ndarray, rasterio.Affine, str]:
    """Read a band aligned to the reference raster grid (reprojected if needed)."""
    with rasterio.open(ref_path) as ref:
        ref_transform = ref.transform
        ref_crs = ref.crs
        ref_w, ref_h = ref.width, ref.height

    with rasterio.open(rf.path) as src:
        if (
            src.crs == ref_crs
            and src.transform == ref_transform
            and src.width == ref_w
            and src.height == ref_h
        ):
            data = src.read(1).astype(np.float32)
            nodata = src.nodata
        else:
            data = np.full((ref_h, ref_w), np.nan, dtype=np.float32)
            reproject(
                source=rasterio.band(src, 1),
                destination=data,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=ref_transform,
                dst_crs=ref_crs,
                resampling=Resampling.bilinear,
            )
            nodata = src.nodata
        if nodata is not None:
            data = np.where(data == nodata, np.nan, data)
    return data, ref_transform, str(ref_crs)


def _save_vi_raster(
    out_path: Path,
    array: np.ndarray,
    ref_path: Path,
) -> None:
    with rasterio.open(ref_path) as ref:
        profile = ref.profile.copy()
    profile.update(dtype="float32", count=1, nodata=np.nan, compress="lzw")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(array.astype(np.float32), 1)


def _group_rasters(files: Iterable[RasterFile]) -> dict[tuple[str, date], list[RasterFile]]:
    groups: dict[tuple[str, date], list[RasterFile]] = {}
    for rf in files:
        if rf.sensor != "MS":
            continue  # only MS bands feed VI math; RGB mosaics ignored for stats
        groups.setdefault((rf.location, rf.date), []).append(rf)
    return groups


def run_pipeline(cfg: PipelineConfig) -> Path:
    cfg.output_folder.mkdir(parents=True, exist_ok=True)

    _log(cfg, f"Scanning raster folder: {cfg.raster_folder}")
    rasters = scan_folder(cfg.raster_folder)
    if not rasters:
        raise ValueError(f"No recognized rasters found in {cfg.raster_folder}")
    _log(cfg, f"Found {len(rasters)} recognized raster file(s).")

    _log(cfg, f"Reading shapefile: {cfg.shapefile}")
    plots_raw = gpd.read_file(cfg.shapefile)
    plot_id_col = _detect_plot_id_column(plots_raw, cfg.plot_id_col)
    _log(cfg, f"Using PlotID column from shapefile: {plot_id_col!r}")

    _log(cfg, f"Reading field data: {cfg.field_excel}")
    field_df = pd.read_excel(cfg.field_excel)
    field_id_col = _detect_plot_id_column(field_df, cfg.plot_id_col or plot_id_col)
    _log(cfg, f"Using PlotID column from Excel: {field_id_col!r}")

    long_rows: list[dict] = []
    groups = _group_rasters(rasters)
    _log(cfg, f"Processing {len(groups)} location/date group(s).")

    for (location, dt), files in sorted(groups.items()):
        _log(cfg, f"--- {location} {dt.isoformat()}: {len(files)} band(s)")
        # Pick the first available band as the geometric reference grid.
        ref_path = files[0].path
        plots = plots_raw.to_crs(rasterio.open(ref_path).crs)

        bands: dict[str, np.ndarray] = {}
        transform = None
        for rf in files:
            arr, tfm, _crs = _load_band_array(rf, ref_path)
            bands[rf.band] = arr
            transform = tfm
            _log(cfg, f"   loaded band: {rf.band}")

        # Zonal stats on each raw band.
        for band_name, arr in bands.items():
            stats_rows = extract_stats_from_array(arr, transform, plots, plot_id_col)
            for r in stats_rows:
                long_rows.append(
                    {
                        "PlotID": r[plot_id_col],
                        "location": location,
                        "date": dt.isoformat(),
                        "layer": band_name,
                        **{k: v for k, v in r.items() if k != plot_id_col},
                    }
                )

        # Compute VIs and run zonal stats on each.
        for vi_name, vi_array in compute_indices(bands):
            _log(cfg, f"   computed VI: {vi_name}")
            if cfg.save_vi_rasters:
                out = cfg.output_folder / "VI_rasters" / f"{location}_{dt:%m%d%Y}_{vi_name}.tif"
                _save_vi_raster(out, vi_array, ref_path)
            stats_rows = extract_stats_from_array(vi_array, transform, plots, plot_id_col)
            for r in stats_rows:
                long_rows.append(
                    {
                        "PlotID": r[plot_id_col],
                        "location": location,
                        "date": dt.isoformat(),
                        "layer": vi_name,
                        **{k: v for k, v in r.items() if k != plot_id_col},
                    }
                )

    long_df = pd.DataFrame(long_rows)
    if long_df.empty:
        raise RuntimeError("No statistics were computed — check that plots intersect the rasters.")

    from .excel import write_workbook

    out_path = cfg.output_folder / "VI_statistics.xlsx"
    _log(cfg, f"Writing Excel: {out_path}")
    write_workbook(long_df, field_df, field_id_col, out_path)
    _log(cfg, "Done.")
    return out_path
