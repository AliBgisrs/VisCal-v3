"""Parse multispectral filenames into (location, sensor, date, band)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

# Canonical band keys we understand
BAND_ALIASES = {
    "blue": "blue",
    "green": "green",
    "red": "red",
    "rededge": "rededge",
    "red edge": "rededge",
    "red_edge": "rededge",
    "nir": "nir",
}

# Example: Irridrain_MS_06262025_transparent_reflectance_nir.tif
#          Irridrain_RGB_06262025_transparent_mosaic_group1.tif
_MS_RE = re.compile(
    r"^(?P<loc>[A-Za-z0-9]+)_(?P<sensor>MS)_(?P<date>\d{8})_transparent_reflectance_(?P<band>.+?)\.tif$",
    re.IGNORECASE,
)
_RGB_RE = re.compile(
    r"^(?P<loc>[A-Za-z0-9]+)_(?P<sensor>RGB)_(?P<date>\d{8})_transparent_mosaic_.+\.tif$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RasterFile:
    path: Path
    location: str
    sensor: str  # "MS" or "RGB"
    date: date
    band: str  # canonical key

    @property
    def group_key(self) -> tuple[str, str, date]:
        return (self.location, self.sensor, self.date)


def _parse_date(token: str) -> date:
    # MMDDYYYY
    return date(int(token[4:8]), int(token[0:2]), int(token[2:4]))


def _normalize_band(raw: str) -> Optional[str]:
    key = raw.lower().strip().replace("-", " ")
    key = re.sub(r"\s+", " ", key)
    if key in BAND_ALIASES:
        return BAND_ALIASES[key]
    compact = key.replace(" ", "")
    return BAND_ALIASES.get(compact)


def parse_filename(path: Path) -> Optional[RasterFile]:
    name = path.name
    m = _MS_RE.match(name)
    if m:
        band = _normalize_band(m.group("band"))
        if not band:
            return None
        return RasterFile(
            path=path,
            location=m.group("loc"),
            sensor="MS",
            date=_parse_date(m.group("date")),
            band=band,
        )
    m = _RGB_RE.match(name)
    if m:
        return RasterFile(
            path=path,
            location=m.group("loc"),
            sensor="RGB",
            date=_parse_date(m.group("date")),
            band="rgb",
        )
    return None


def scan_folder(folder: Path) -> list[RasterFile]:
    out: list[RasterFile] = []
    for p in sorted(folder.iterdir()):
        if p.is_file() and p.suffix.lower() in (".tif", ".tiff"):
            rf = parse_filename(p)
            if rf is not None:
                out.append(rf)
    return out
