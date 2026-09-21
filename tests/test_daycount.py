"""Day-count conventions vs hand-computed values."""
import numpy as np
import pytest
from src.common.calendar import to_days
from src.common.daycount import year_fraction, days_30e360, ACT365, ACTACT, E30360


def yf(a, b, conv):
    return float(year_fraction(to_days([a])[0], to_days([b])[0], conv))


def test_act365_counts_actual_days_over_365_even_in_leap_year():
    assert yf("2024-01-01", "2024-03-01", ACT365) == pytest.approx(60 / 365)     # 31 + 29 days


def test_actact_uses_366_in_leap_year():
    assert yf("2024-02-01", "2024-03-01", ACTACT) == pytest.approx(29 / 366)


def test_actact_splits_across_year_end():
    # 17-Dec-2023 .. 16-Jan-2024: 15 days in 2023 (/365) + 15 days in 2024 (/366)
    assert yf("2023-12-17", "2024-01-16", ACTACT) == pytest.approx(15 / 365 + 15 / 366)


def test_actact_full_leap_year_is_exactly_one():
    assert yf("2024-01-01", "2025-01-01", ACTACT) == pytest.approx(1.0)


@pytest.mark.parametrize("a,b,expected", [
    ("2024-01-01", "2024-02-01", 30),     # any whole month = 30
    ("2024-02-01", "2024-03-01", 30),     # February too
    ("2024-01-31", "2024-03-01", 31),     # D1 31 -> 30: 60 + (1 - 30)
    ("2024-02-28", "2024-03-31", 32),     # D2 31 -> 30: 30 + (30 - 28)
    ("2023-01-15", "2024-01-15", 360),
])
def test_30e360(a, b, expected):
    assert int(days_30e360(to_days([a]), to_days([b]))[0]) == expected
    assert yf(a, b, E30360) == pytest.approx(expected / 360)


def test_30e360_is_additive_so_segments_can_be_summed():
    s, m, e = to_days(["2024-01-10", "2024-01-31", "2024-02-20"])
    assert days_30e360(s, m) + days_30e360(m, e) == days_30e360(s, e)
