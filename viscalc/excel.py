"""Pivot long-form statistics into a multi-sheet Excel workbook joined with field data."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from .zonal import PERCENTILES

STAT_SHEETS = ["mean", "median", "min", "max"]


def _pivot(long_df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    wide = long_df.pivot_table(
        index="PlotID",
        columns=["date", "layer"],
        values=value_col,
        aggfunc="first",
    )
    wide.columns = [f"{date}_{layer}" for date, layer in wide.columns]
    wide = wide.sort_index(axis=1)
    return wide.reset_index()


def _pivot_percentiles(long_df: pd.DataFrame) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    for p in PERCENTILES:
        col = f"P{p}"
        wide = long_df.pivot_table(
            index="PlotID",
            columns=["date", "layer"],
            values=col,
            aggfunc="first",
        )
        wide.columns = [f"{date}_{layer}_P{p}" for date, layer in wide.columns]
        parts.append(wide)
    combined = pd.concat(parts, axis=1).sort_index(axis=1).reset_index()
    return combined


def _merge_with_field(stats_df: pd.DataFrame, field_df: pd.DataFrame, field_id_col: str) -> pd.DataFrame:
    field = field_df.rename(columns={field_id_col: "PlotID"})
    # Cast both PlotID columns to string for tolerant matching.
    stats_df = stats_df.copy()
    stats_df["PlotID"] = stats_df["PlotID"].astype(str)
    field["PlotID"] = field["PlotID"].astype(str)
    return field.merge(stats_df, on="PlotID", how="left")


def write_workbook(
    long_df: pd.DataFrame,
    field_df: pd.DataFrame,
    field_id_col: str,
    out_path: Path,
) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(out_path, engine="openpyxl") as xls:
        for stat in STAT_SHEETS:
            wide = _pivot(long_df, stat)
            merged = _merge_with_field(wide, field_df, field_id_col)
            merged.to_excel(xls, sheet_name=stat, index=False)
        pct_wide = _pivot_percentiles(long_df)
        merged = _merge_with_field(pct_wide, field_df, field_id_col)
        merged.to_excel(xls, sheet_name="percentiles", index=False)
