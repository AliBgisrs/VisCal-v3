"""Vegetation index formulas. Each takes a dict of band arrays and returns
(name, array) tuples for every index that can be computed from what is present.
"""
from __future__ import annotations

from typing import Iterator

import numpy as np

BAND_REQS = {
    "NDVI": ("nir", "red"),
    "GNDVI": ("nir", "green"),
    "NDRE": ("nir", "rededge"),
    "CIRE": ("nir", "rededge"),
    "GCI": ("nir", "green"),
    "SAVI": ("nir", "red"),
    "OSAVI": ("nir", "red"),
    "MSAVI": ("nir", "red"),
    "MCARI": ("rededge", "red", "green"),
    "NDREI": ("rededge", "green"),
}


def _safe_divide(num: np.ndarray, den: np.ndarray) -> np.ndarray:
    out = np.full(num.shape, np.nan, dtype=np.float32)
    mask = np.isfinite(num) & np.isfinite(den) & (den != 0)
    out[mask] = num[mask] / den[mask]
    return out


def compute_indices(bands: dict[str, np.ndarray]) -> Iterator[tuple[str, np.ndarray]]:
    """Yield (name, array) for each index whose bands are available."""
    def has(*names: str) -> bool:
        return all(n in bands for n in names)

    if has("nir", "red"):
        nir, red = bands["nir"], bands["red"]
        yield "NDVI", _safe_divide(nir - red, nir + red)
        L = 0.5
        yield "SAVI", _safe_divide((nir - red) * (1 + L), nir + red + L)
        yield "OSAVI", _safe_divide(nir - red, nir + red + 0.16) * (1 + 0.16)
        inside = (2 * nir + 1) ** 2 - 8 * (nir - red)
        inside = np.where(inside < 0, np.nan, inside)
        yield "MSAVI", (2 * nir + 1 - np.sqrt(inside)) / 2

    if has("nir", "green"):
        nir, green = bands["nir"], bands["green"]
        yield "GNDVI", _safe_divide(nir - green, nir + green)
        yield "GCI", _safe_divide(nir, green) - 1

    if has("nir", "rededge"):
        nir, re = bands["nir"], bands["rededge"]
        yield "NDRE", _safe_divide(nir - re, nir + re)
        yield "CIRE", _safe_divide(nir, re) - 1

    if has("rededge", "green"):
        re, green = bands["rededge"], bands["green"]
        yield "NDREI", _safe_divide(re - green, re + green)

    if has("rededge", "red", "green"):
        re, red, green = bands["rededge"], bands["red"], bands["green"]
        yield "MCARI", ((re - red) - 0.2 * (re - green)) * _safe_divide(re, red)
