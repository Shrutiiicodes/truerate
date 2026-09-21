"""Day-count conventions (vectorised). Dates are int days; periods are [start, end).

ACT/365F : actual days / 365 in every year.
ACT/ACT  : ISDA style - days falling in each calendar year / that year's length.
30E/360  : Eurobond basis; D1 and D2 capped at 30.
"""
from __future__ import annotations
import numpy as np
from .calendar import from_days, year_of, year_start, days_in_year

ACT365 = "ACT/365F"
ACTACT = "ACT/ACT"
E30360 = "30E/360"
CODE = {ACT365: 0, ACTACT: 1, E30360: 2}


def actual_days(start, end) -> np.ndarray:
    return np.asarray(end, dtype=np.int64) - np.asarray(start, dtype=np.int64)


def days_30e360(start, end) -> np.ndarray:
    s, e = from_days(start), from_days(end)
    y1 = s.astype("datetime64[Y]").astype(np.int64)
    y2 = e.astype("datetime64[Y]").astype(np.int64)
    m1 = s.astype("datetime64[M]").astype(np.int64) - y1 * 12
    m2 = e.astype("datetime64[M]").astype(np.int64) - y2 * 12
    d1 = np.minimum((s - s.astype("datetime64[M]").astype("datetime64[D]")).astype(np.int64) + 1, 30)
    d2 = np.minimum((e - e.astype("datetime64[M]").astype("datetime64[D]")).astype(np.int64) + 1, 30)
    return 360 * (y2 - y1) + 30 * (m2 - m1) + (d2 - d1)


def year_fraction(start, end, convention: str) -> np.ndarray:
    """General year fraction for [start, end), may span year ends."""
    start = np.asarray(start, dtype=np.int64)
    end = np.asarray(end, dtype=np.int64)
    if convention == ACT365:
        return actual_days(start, end) / 365.0
    if convention == E30360:
        return days_30e360(start, end) / 360.0
    if convention == ACTACT:
        y1, y2 = year_of(start), year_of(end - 1)
        f_same = (end - start) / days_in_year(y1)
        first = (year_start(y1 + 1) - start) / days_in_year(y1)
        last = (end - year_start(y2)) / days_in_year(y2)
        return np.where(y1 == y2, f_same, first + (y2 - y1 - 1) + last)
    raise ValueError(f"Unknown convention {convention}")


def year_basis(start, code, force_365=None) -> np.ndarray:
    """Year basis for a segment lying inside one calendar year.
    Codes: 0 ACT/365F -> 365; 1 ACT/ACT -> 365 or 366; 2 30E/360 -> 360."""
    code = np.asarray(code)
    diy = days_in_year(year_of(start))
    if force_365 is not None:
        diy = np.where(force_365, 365, diy)
    return np.select([code == 0, code == 1, code == 2], [365, diy, 360]).astype(float)


def day_count(start, end, code) -> np.ndarray:
    """Numerator for [start, end) under the convention code."""
    code = np.asarray(code)
    act = actual_days(start, end)
    if np.any(code == 2):
        return np.where(code == 2, days_30e360(start, end), act)
    return act
