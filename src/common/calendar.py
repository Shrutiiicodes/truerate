"""Date helpers on int64 'days since 1970-01-01'.

Billing periods are calendar months. A month index counts months from
Jan-2021 (index 0), matching the observation window.
"""
from __future__ import annotations
import numpy as np

BASE_YEAR = 2021


def to_days(dates) -> np.ndarray:
    """Convert date-like values (ISO strings, datetime64, pandas) to int64 days since 1970-01-01."""
    arr = np.asarray(getattr(dates, "to_numpy", lambda: dates)())
    if arr.dtype.kind in "OUS":
        arr = arr.astype(str).astype("datetime64[D]")
    return arr.astype("datetime64[D]").astype(np.int64)


def from_days(days) -> np.ndarray:
    return np.asarray(days, dtype=np.int64).astype("datetime64[D]")


def month_index(days) -> np.ndarray:
    """Month index (0 = Jan-2021) of each date given as int days."""
    m = from_days(days).astype("datetime64[M]").astype(np.int64)
    return m - ((BASE_YEAR - 1970) * 12)


def month_start(idx) -> np.ndarray:
    """First day (int days) of month index `idx`."""
    months = np.asarray(idx, dtype=np.int64) + (BASE_YEAR - 1970) * 12
    return months.astype("datetime64[M]").astype("datetime64[D]").astype(np.int64)


def period_label(idx) -> np.ndarray:
    months = np.asarray(idx, dtype=np.int64) + (BASE_YEAR - 1970) * 12
    return months.astype("datetime64[M]").astype(str)


def add_months(days, k) -> np.ndarray:
    """Shift dates by k months, clipping the day to the target month's length
    (e.g. 31-Jan + 1 month = 28/29-Feb)."""
    d = from_days(days)
    m0 = d.astype("datetime64[M]")
    dom = (d - m0.astype("datetime64[D]")).astype(np.int64)
    m1 = m0 + np.asarray(k, dtype=np.int64)
    start = m1.astype("datetime64[D]")
    dim = ((m1 + 1).astype("datetime64[D]") - start).astype(np.int64)
    return (start + np.minimum(dom, dim - 1)).astype(np.int64)


def year_of(days) -> np.ndarray:
    return from_days(days).astype("datetime64[Y]").astype(np.int64) + 1970


def year_start(year) -> np.ndarray:
    y = np.asarray(year, dtype=np.int64) - 1970
    return y.astype("datetime64[Y]").astype("datetime64[D]").astype(np.int64)


def is_leap(year) -> np.ndarray:
    y = np.asarray(year)
    return ((y % 4 == 0) & (y % 100 != 0)) | (y % 400 == 0)


def days_in_year(year) -> np.ndarray:
    return np.where(is_leap(year), 366, 365)
