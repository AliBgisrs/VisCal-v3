"""Per-plot zonal statistics extraction."""
from __future__ import annotations

from typing import Iterable

import numpy as np
import rasterio
from rasterio.features import geometry_mask
from rasterio.windows import from_bounds

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


def extract_stats(
    raster_path,
    band_index: int,
    plots,  # GeoDataFrame already reprojected to raster CRS
    plot_id_col: str,
    nodata_override: float | None = None,
) -> list[dict]:
    """Return one dict per plot with stats and the plot id."""
    rows: list[dict] = []
    with rasterio.open(raster_path) as src:
        for _, plot in plots.iterrows():
            geom = plot.geometry
            if geom is None or geom.is_empty:
                continue
            try:
                window = from_bounds(*geom.bounds, transform=src.transform)
                window = window.round_offsets().round_lengths()
                window = window.intersection(
                    rasterio.windows.Window(0, 0, src.width, src.height)
                )
            except (ValueError, rasterio.errors.WindowError):
                continue
            if window.width <= 0 or window.height <= 0:
                continue
            data = src.read(band_index, window=window).astype(np.float32)
            nodata = nodata_override if nodata_override is not None else src.nodata
            if nodata is not None:
                data = np.where(data == nodata, np.nan, data)
            transform = src.window_transform(window)
            mask = geometry_mask(
                [geom],
                out_shape=data.shape,
                transform=transform,
                invert=True,
                all_touched=False,
            )
            values = data[mask]
            stats = _stats_for_pixels(values)
            stats[plot_id_col] = plot[plot_id_col]
            rows.append(stats)
    return rows


def extract_stats_from_array(
    array: np.ndarray,
    transform,
    plots,
    plot_id_col: str,
) -> list[dict]:
    """Same as extract_stats but for an in-memory array (used for VI rasters)."""
    rows: list[dict] = []
    for _, plot in plots.iterrows():
        geom = plot.geometry
        if geom is None or geom.is_empty:
            continue
        mask = geometry_mask(
            [geom], out_shape=array.shape, transform=transform, invert=True
        )
        values = array[mask]
        stats = _stats_for_pixels(values)
        stats[plot_id_col] = plot[plot_id_col]
        rows.append(stats)
    return rows
