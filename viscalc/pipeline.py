"""Streaming pipeline: never loads full bands into RAM.

For each (location, sensor, date) group:
 - Open band files as rasterio handles (wrap in WarpedVRT if grids differ).
 - For every plot, read only its windowed sub-array from each band.
 - Compute VIs in that small window, mask with the plot polygon, gather stats.
 - If VI rasters are requested, run a second tile-by-tile pass that writes the
   selected VIs as compressed tiled GeoTIFFs (memory bounded by tile size).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import geometry_mask
from rasterio.vrt import WarpedVRT
from rasterio.warp import Resampling
from rasterio.windows import Window, transform as window_transform

from .indices import compute_indices, compute_rgb_indices
from .parser import RasterFile, scan_folder
from .zonal import _plot_window, _stats_for_pixels

log = logging.getLogger(__name__)

DEFAULT_TILE_SIZE = 1024  # pixels, used when writing VI rasters


@dataclass
class PipelineConfig:
    raster_folder: Path
    shapefile: Path
    field_excel: Path
    output_folder: Path
    plot_id_col: Optional[str] = None
    save_vi_rasters: bool = False
    vis_to_save: Optional[set[str]] = None
    tile_size: int = DEFAULT_TILE_SIZE
    progress: Optional[Callable[[str], None]] = None
    progress_pct: Optional[Callable[[float], None]] = None  # 0-100
    status: Optional[Callable[[str], None]] = None

    def should_save(self, vi_name: str) -> bool:
        if not self.save_vi_rasters:
            return False
        if self.vis_to_save is None:
            return True
        return vi_name in self.vis_to_save


def _log(cfg: PipelineConfig, msg: str) -> None:
    log.info(msg)
    if cfg.progress is not None:
        cfg.progress(msg)


def _set_status(cfg: PipelineConfig, msg: str) -> None:
    if cfg.status is not None:
        cfg.status(msg)


def _set_pct(cfg: PipelineConfig, pct: float) -> None:
    if cfg.progress_pct is not None:
        cfg.progress_pct(max(0.0, min(100.0, pct)))


def _detect_plot_id_column(df: pd.DataFrame, hint: Optional[str]) -> str:
    if hint and hint in df.columns:
        return hint
    cands = [c for c in df.columns if str(c).lower().replace("_", "") in ("plotid", "plot")]
    if cands:
        return cands[0]
    raise ValueError(
        f"Could not find a PlotID column in {list(df.columns)}. "
        "Rename the column to 'PlotID' or pass plot_id_col explicitly."
    )


def _group_rasters(
    files: Iterable[RasterFile],
) -> dict[tuple[str, str, date], list[RasterFile]]:
    groups: dict[tuple[str, str, date], list[RasterFile]] = {}
    for rf in files:
        groups.setdefault((rf.location, rf.sensor, rf.date), []).append(rf)
    return groups


# ----------------------------------------------------------------------------
# Streaming readers
# ----------------------------------------------------------------------------


def _open_band(rf: RasterFile, ref_ds) -> "rasterio.io.DatasetReader":
    """Open band as a reader. If grid != reference, wrap in WarpedVRT so windowed
    reads come back on the reference grid without materializing the full raster."""
    src = rasterio.open(rf.path)
    if (
        src.crs == ref_ds.crs
        and src.transform == ref_ds.transform
        and src.width == ref_ds.width
        and src.height == ref_ds.height
    ):
        return src
    vrt = WarpedVRT(
        src,
        crs=ref_ds.crs,
        transform=ref_ds.transform,
        width=ref_ds.width,
        height=ref_ds.height,
        resampling=Resampling.bilinear,
    )
    # WarpedVRT keeps the source open via the parent; closing the VRT is enough.
    return vrt


def _read_band_window(
    src, window: Window, band_index: int = 1
) -> np.ndarray:
    data = src.read(band_index, window=window).astype(np.float32)
    if src.nodata is not None:
        data[data == src.nodata] = np.nan
    return data


def _progress_ticks(n: int) -> set[int]:
    if n <= 10:
        return set(range(1, n + 1))
    step = max(1, n // 10)
    return {i for i in range(step, n + 1, step)} | {n}


class _Progress:
    """Tracks fractional progress across the whole run."""
    def __init__(self, cfg: PipelineConfig, total_units: float):
        self.cfg = cfg
        self.total = max(1.0, float(total_units))
        self.done = 0.0

    def tick(self, units: float = 1.0) -> None:
        self.done += units
        _set_pct(self.cfg, 100.0 * self.done / self.total)


# ----------------------------------------------------------------------------
# Per-plot zonal pass
# ----------------------------------------------------------------------------


def _zonal_streaming_ms(
    cfg: PipelineConfig,
    srcs: dict[str, "rasterio.io.DatasetReader"],
    location: str,
    dt: date,
    plots,
    plot_id_col: str,
    out_rows: list[dict],
    progress: Optional["_Progress"] = None,
) -> None:
    ref = next(iter(srcs.values()))
    H, W = ref.height, ref.width
    n = len(plots)
    ticks = _progress_ticks(n)
    _set_status(cfg, f"Zonal stats: {location} {dt.isoformat()} (MS)")
    _log(cfg, f"   running zonal stats over {n} plot(s)...")

    for i, (_, plot) in enumerate(plots.iterrows(), 1):
        geom = plot.geometry
        if geom is None or geom.is_empty:
            continue
        win = _plot_window(geom, ref.transform, H, W)
        if win is None:
            continue
        r0, r1, c0, c1 = win
        window = Window(c0, r0, c1 - c0, r1 - r0)
        sub_transform = window_transform(window, ref.transform)

        bands_w: dict[str, np.ndarray] = {}
        for band_name, src in srcs.items():
            bands_w[band_name] = _read_band_window(src, window)

        shape = next(iter(bands_w.values())).shape
        mask = geometry_mask(
            [geom], out_shape=shape, transform=sub_transform, invert=True
        )

        pid = plot[plot_id_col]
        for band_name, arr in bands_w.items():
            stats = _stats_for_pixels(arr[mask])
            stats[plot_id_col] = pid
            out_rows.append(
                {"PlotID": pid, "location": location, "date": dt.isoformat(),
                 "layer": band_name,
                 **{k: v for k, v in stats.items() if k != plot_id_col}}
            )

        for vi_name, vi_arr in compute_indices(bands_w):
            stats = _stats_for_pixels(vi_arr[mask])
            stats[plot_id_col] = pid
            out_rows.append(
                {"PlotID": pid, "location": location, "date": dt.isoformat(),
                 "layer": vi_name,
                 **{k: v for k, v in stats.items() if k != plot_id_col}}
            )

        if progress is not None:
            progress.tick(1.0)
        if i in ticks:
            _log(cfg, f"      plot {i}/{n}")


def _zonal_streaming_rgb(
    cfg: PipelineConfig,
    src,
    location: str,
    dt: date,
    plots,
    plot_id_col: str,
    out_rows: list[dict],
    progress: Optional["_Progress"] = None,
) -> None:
    H, W = src.height, src.width
    n = len(plots)
    ticks = _progress_ticks(n)
    has_alpha = src.count >= 4
    _set_status(cfg, f"Zonal stats: {location} {dt.isoformat()} (RGB)")
    _log(cfg, f"   running RGB zonal stats over {n} plot(s)...")

    for i, (_, plot) in enumerate(plots.iterrows(), 1):
        geom = plot.geometry
        if geom is None or geom.is_empty:
            continue
        win = _plot_window(geom, src.transform, H, W)
        if win is None:
            continue
        r0, r1, c0, c1 = win
        window = Window(c0, r0, c1 - c0, r1 - r0)
        sub_transform = window_transform(window, src.transform)

        R = src.read(1, window=window).astype(np.float32)
        G = src.read(2, window=window).astype(np.float32)
        B = src.read(3, window=window).astype(np.float32)
        if src.nodata is not None:
            for arr in (R, G, B):
                arr[arr == src.nodata] = np.nan
        if has_alpha:
            alpha = src.read(4, window=window)
            invalid = alpha == 0
            for arr in (R, G, B):
                arr[invalid] = np.nan

        bands_w = {"R": R, "G": G, "B": B}
        mask = geometry_mask(
            [geom], out_shape=R.shape, transform=sub_transform, invert=True
        )

        pid = plot[plot_id_col]
        for band_name, arr in bands_w.items():
            stats = _stats_for_pixels(arr[mask])
            stats[plot_id_col] = pid
            out_rows.append(
                {"PlotID": pid, "location": location, "date": dt.isoformat(),
                 "layer": f"RGB_{band_name}",
                 **{k: v for k, v in stats.items() if k != plot_id_col}}
            )

        for vi_name, vi_arr in compute_rgb_indices(bands_w):
            stats = _stats_for_pixels(vi_arr[mask])
            stats[plot_id_col] = pid
            out_rows.append(
                {"PlotID": pid, "location": location, "date": dt.isoformat(),
                 "layer": vi_name,
                 **{k: v for k, v in stats.items() if k != plot_id_col}}
            )

        if progress is not None:
            progress.tick(1.0)
        if i in ticks:
            _log(cfg, f"      plot {i}/{n}")


# ----------------------------------------------------------------------------
# Tiled VI raster export
# ----------------------------------------------------------------------------


def _profile_for_vi(ref_ds, tile: int) -> dict:
    profile = ref_ds.profile.copy()
    profile.update(
        dtype="float32",
        count=1,
        nodata=np.nan,
        compress="lzw",
        tiled=True,
        blockxsize=min(512, ref_ds.width if ref_ds.width >= 512 else ref_ds.width),
        blockysize=min(512, ref_ds.height if ref_ds.height >= 512 else ref_ds.height),
    )
    for k in ("photometric", "interleave"):
        profile.pop(k, None)
    return profile


def _save_vis_tiled_ms(
    cfg: PipelineConfig,
    srcs: dict[str, "rasterio.io.DatasetReader"],
    location: str,
    dt: date,
    progress: Optional["_Progress"] = None,
) -> None:
    if not cfg.save_vi_rasters or not cfg.vis_to_save:
        return
    ref = next(iter(srcs.values()))
    H, W = ref.height, ref.width
    tile = cfg.tile_size
    out_dir = cfg.output_folder / "VI_rasters"
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = _profile_for_vi(ref, tile)
    writers: dict[str, "rasterio.io.DatasetWriter"] = {}
    _set_status(cfg, f"Writing VI rasters: {location} {dt.isoformat()} (MS)")
    try:
        for vi in cfg.vis_to_save:
            out_path = out_dir / f"{location}_{dt:%m%d%Y}_{vi}.tif"
            writers[vi] = rasterio.open(out_path, "w", **profile)
            _log(cfg, f"   writing VI raster: {out_path.name}")

        for y in range(0, H, tile):
            for x in range(0, W, tile):
                w = Window(x, y, min(tile, W - x), min(tile, H - y))
                bands_tile = {bn: _read_band_window(src, w) for bn, src in srcs.items()}
                for vi_name, vi_arr in compute_indices(bands_tile):
                    if vi_name in writers:
                        writers[vi_name].write(vi_arr.astype(np.float32), 1, window=w)
                if progress is not None:
                    progress.tick(1.0)
    finally:
        for w in writers.values():
            w.close()


def _save_vis_tiled_rgb(
    cfg: PipelineConfig,
    src,
    location: str,
    dt: date,
    progress: Optional["_Progress"] = None,
) -> None:
    if not cfg.save_vi_rasters or not cfg.vis_to_save:
        return
    H, W = src.height, src.width
    tile = cfg.tile_size
    out_dir = cfg.output_folder / "VI_rasters"
    out_dir.mkdir(parents=True, exist_ok=True)
    profile = _profile_for_vi(src, tile)
    writers: dict[str, "rasterio.io.DatasetWriter"] = {}
    has_alpha = src.count >= 4
    _set_status(cfg, f"Writing VI rasters: {location} {dt.isoformat()} (RGB)")
    try:
        for vi in cfg.vis_to_save:
            out_path = out_dir / f"{location}_{dt:%m%d%Y}_{vi}.tif"
            writers[vi] = rasterio.open(out_path, "w", **profile)
            _log(cfg, f"   writing VI raster: {out_path.name}")

        for y in range(0, H, tile):
            for x in range(0, W, tile):
                w = Window(x, y, min(tile, W - x), min(tile, H - y))
                R = src.read(1, window=w).astype(np.float32)
                G = src.read(2, window=w).astype(np.float32)
                B = src.read(3, window=w).astype(np.float32)
                if src.nodata is not None:
                    for arr in (R, G, B):
                        arr[arr == src.nodata] = np.nan
                if has_alpha:
                    alpha = src.read(4, window=w)
                    invalid = alpha == 0
                    for arr in (R, G, B):
                        arr[invalid] = np.nan
                bands_tile = {"R": R, "G": G, "B": B}
                for vi_name, vi_arr in compute_rgb_indices(bands_tile):
                    if vi_name in writers:
                        writers[vi_name].write(vi_arr.astype(np.float32), 1, window=w)
                if progress is not None:
                    progress.tick(1.0)
    finally:
        for w in writers.values():
            w.close()


# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------


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
    _log(cfg, f"Processing {len(groups)} location/sensor/date group(s).")

    # --- estimate total work units for the progress bar ---------------------
    n_plots_overall = len(plots_raw)
    total_units = 0.0
    # Each plot iteration ≈ 1 unit.
    for _key, files in groups.items():
        total_units += n_plots_overall
    # If saving VI rasters, add an estimate of tile writes per group.
    if cfg.save_vi_rasters and cfg.vis_to_save:
        for _key, files in groups.items():
            try:
                with rasterio.open(files[0].path) as probe:
                    nx = max(1, (probe.width + cfg.tile_size - 1) // cfg.tile_size)
                    ny = max(1, (probe.height + cfg.tile_size - 1) // cfg.tile_size)
                    total_units += nx * ny
            except Exception:
                pass
    progress = _Progress(cfg, total_units)
    _set_pct(cfg, 0.0)
    _set_status(cfg, "Starting...")

    for (location, sensor, dt), files in sorted(groups.items()):
        _log(cfg, f"--- {location} {sensor} {dt.isoformat()}: {len(files)} file(s)")

        if sensor == "MS":
            ref_path = files[0].path
            ref_ds = rasterio.open(ref_path)
            try:
                srcs: dict[str, "rasterio.io.DatasetReader"] = {files[0].band: ref_ds}
                for rf in files[1:]:
                    srcs[rf.band] = _open_band(rf, ref_ds)
                _log(cfg, f"   opened bands: {', '.join(srcs)}")
                plots = plots_raw.to_crs(ref_ds.crs)
                _log(cfg, f"   plots reprojected: {len(plots)} polygon(s)")

                _zonal_streaming_ms(cfg, srcs, location, dt, plots, plot_id_col,
                                    long_rows, progress=progress)
                _save_vis_tiled_ms(cfg, srcs, location, dt, progress=progress)
            finally:
                for s in srcs.values():
                    try:
                        s.close()
                    except Exception:
                        pass

        elif sensor == "RGB":
            for rf in files:
                with rasterio.open(rf.path) as src:
                    _log(cfg, f"   opened RGB mosaic: {rf.path.name}  {src.width}x{src.height}")
                    plots = plots_raw.to_crs(src.crs)
                    _zonal_streaming_rgb(cfg, src, location, dt, plots, plot_id_col,
                                         long_rows, progress=progress)
                    _save_vis_tiled_rgb(cfg, src, location, dt, progress=progress)
        else:
            _log(cfg, f"   skipping unknown sensor: {sensor}")

    if not long_rows:
        raise RuntimeError("No statistics were computed — check that plots intersect the rasters.")

    long_df = pd.DataFrame(long_rows)

    from .excel import write_workbook

    out_path = cfg.output_folder / "VI_statistics.xlsx"
    _set_status(cfg, "Writing Excel...")
    _log(cfg, f"Writing Excel: {out_path}")
    write_workbook(long_df, field_df, field_id_col, out_path)
    _set_pct(cfg, 100.0)
    _set_status(cfg, "Done")
    _log(cfg, "Done.")
    return out_path
