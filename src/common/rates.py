"""Benchmark and spread lookups. A change effective on date D applies ON D."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .calendar import to_days


class StepCurve:
    """Piecewise-constant series keyed by effective date (int days)."""

    def __init__(self, dates_days, values):
        order = np.argsort(dates_days, kind="stable")
        self.dates = np.asarray(dates_days, dtype=np.int64)[order]
        self.values = np.asarray(values, dtype=float)[order]

    def at(self, days) -> np.ndarray:
        d = np.asarray(days, dtype=np.int64)
        idx = np.searchsorted(self.dates, d, side="right") - 1
        if np.any(idx < 0):
            raise ValueError("Lookup date before start of series")
        return self.values[idx]


def load_benchmark_curves(bench: pd.DataFrame) -> dict:
    return {name: StepCurve(to_days(g["effective_date"].astype(str)), g["rate_pct"].values)
            for name, g in bench.groupby("benchmark")}


def spread_curve(spread_history):
    if not spread_history:
        return None
    d = to_days([str(x["effective_from"]) for x in spread_history])
    return StepCurve(d, [x["spread_pct"] for x in spread_history])


def lookup_by_group(group_codes, days, curves: dict) -> np.ndarray:
    """Each element uses the curve of its group; groups mapped to None return 0."""
    group_codes = np.asarray(group_codes)
    days = np.asarray(days, dtype=np.int64)
    out = np.zeros(len(days), dtype=float)
    for code, curve in curves.items():
        if curve is None:
            continue
        mask = group_codes == code
        if mask.any():
            out[mask] = curve.at(days[mask])
    return out
