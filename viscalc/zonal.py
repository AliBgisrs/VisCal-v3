"""Per-plot zonal statistics extraction.

Each plot is windowed to its bounding box before rasterizing the mask, so
runtime scales with plot area rather than full raster size.
"""
from __future__ import annotations

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import Window, transform as window_transform

PERCENTILES = (10, 25, 50, 75, 90)


def _stats_for_pixels(values: np.ndarray) -> dict[str, float]:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        nan = float("nan")
        out = {"mean": nan, "median": nan, "min": nan, "max": nan, "count": 0}
        for p in PERCENTILES:
            out[f"P{p}"] = nan
        return out
    out = {
        "mean": float(np.mean(finite)),
        "median": float(np.median(finite)),
        "min": float(np.min(finite)),
        "max": float(np.max(finite)),
        "count": int(finite.size),
    }
    pcts = np.percentile(finite, PERCENTILES)
    for p, v in zip(PERCENTILES, pcts):
        out[f"P{p}"] = float(v)
    return out


def _plot_window(geom, transform, height, width) -> tuple[int, int, int, int] | None:
    """Return (row_min, row_max, col_min, col_max) clipped to raster, or None."""
    minx, miny, maxx, maxy = geom.bounds
    inv = ~transform
    c0, r0 = inv * (minx, maxy)
    c1, r1 = inv * (maxx, miny)
    col_min = max(0, int(np.floor(min(c0, c1))))
    col_max = min(width, int(np.ceil(max(c0, c1))))
    row_min = max(0, int(np.floor(min(r0, r1))))
    row_max = min(height, int(np.ceil(max(r0, r1))))
    if col_max <= col_min or row_max <= row_min:
        return None
    return row_min, row_max, col_min, col_max


def extract_stats_from_array(
    array: np.ndarray,
    transform,
    plots,
    plot_id_col: str,
) -> list[dict]:
    """Zonal stats for an in-memory float array. Per-plot windowed for speed."""
    rows: list[dict] = []
    H, W = array.shape
    for _, plot in plots.iterrows():
        geom = plot.geometry
        if geom is None or geom.is_empty:
            continue
        win = _plot_window(geom, transform, H, W)
        if win is None:
            continue
        r0, r1, c0, c1 = win
        sub = array[r0:r1, c0:c1]
        sub_transform = window_transform(Window(c0, r0, c1 - c0, r1 - r0), transform)
        mask = geometry_mask(
            [geom],
            out_shape=sub.shape,
            transform=sub_transform,
            invert=True,
            all_touched=False,
        )
        values = sub[mask]
        stats = _stats_for_pixels(values)
        stats[plot_id_col] = plot[plot_id_col]
        rows.append(stats)
    return rows


def extract_stats(
    raster_path,
    band_index: int,
    plots,
    plot_id_col: str,
    nodata_override: float | None = None,
) -> list[dict]:
    """Direct from-disk variant (only used when an array is not already in memory)."""
    rows: list[dict] = []
    with rasterio.open(raster_path) as src:
        H, W = src.height, src.width
        for _, plot in plots.iterrows():
            geom = plot.geometry
            if geom is None or geom.is_empty:
                continue
            win = _plot_window(geom, src.transform, H, W)
            if win is None:
                continue
            r0, r1, c0, c1 = win
            window = Window(c0, r0, c1 - c0, r1 - r0)
            data = src.read(band_index, window=window).astype(np.float32)
            nodata = nodata_override if nodata_override is not None else src.nodata
            if nodata is not None:
                data = np.where(data == nodata, np.nan, data)
            sub_transform = window_transform(window, src.transform)
            mask = geometry_mask(
                [geom],
                out_shape=data.shape,
                transform=sub_transform,
                invert=True,
                all_touched=False,
            )
            values = data[mask]
            stats = _stats_for_pixels(values)
            stats[plot_id_col] = plot[plot_id_col]
            rows.append(stats)
    return rows
