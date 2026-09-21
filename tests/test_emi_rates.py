"""EMI formula and benchmark lookup on change dates."""
import numpy as np
import pandas as pd
import pytest
from src.common.emi import emi
from src.common.rounding import round_half_up
from src.common.calendar import to_days, add_months
from src.common.rates import load_benchmark_curves
from src.generator.reference import build_benchmarks


def test_emi_known_value():
    # 10 lakh, 12% p.a., 12 months: 88,848.79 by the standard formula -> 88,849 rounded to the rupee
    assert float(emi(1_000_000, 12.0, 12, round_to_rupee=False)) == pytest.approx(88848.79, abs=0.01)
    assert float(emi(1_000_000, 12.0, 12)) == 88849.0


def test_emi_home_loan_value():
    # 50 lakh, 8.5%, 240 months -> 43,391.16 (standard amortisation tables)
    assert float(emi(5_000_000, 8.5, 240, round_to_rupee=False)) == pytest.approx(43391.16, abs=0.01)


def test_emi_zero_rate_is_straight_line():
    assert float(emi(120_000, 0.0, 12)) == 10_000.0


def test_round_half_up_not_bankers():
    assert float(round_half_up(0.125, 2)) == 0.13
    assert float(round_half_up(2.5, 0)) == 3.0
    assert float(round_half_up(-2.5, 0)) == -3.0


@pytest.fixture(scope="module")
def curves():
    return load_benchmark_curves(build_benchmarks())


def test_repo_rate_applies_on_its_effective_date(curves):
    repo = curves["REPO"]
    assert float(repo.at(to_days(["2022-06-07"]))[0]) == 4.40
    assert float(repo.at(to_days(["2022-06-08"]))[0]) == 4.90     # reset exactly on MPC date picks up the new rate
    assert float(repo.at(to_days(["2025-06-06"]))[0]) == 5.50
    assert float(repo.at(to_days(["2023-02-08"]))[0]) == 6.50


def test_repo_history_matches_rbi_dates(curves):
    expected = {"2020-05-22": 4.00, "2022-05-04": 4.40, "2022-06-08": 4.90, "2022-08-05": 5.40, "2022-09-30": 5.90,
                "2022-12-07": 6.25, "2023-02-08": 6.50, "2025-02-07": 6.25, "2025-04-09": 6.00, "2025-06-06": 5.50}
    for d, r in expected.items():
        assert float(curves["REPO"].at(to_days([d]))[0]) == r, d


def test_add_months_clips_to_month_end():
    assert str(np.datetime64(int(add_months(to_days(["2024-01-31"]), 1)[0]), "D")) == "2024-02-29"
    assert str(np.datetime64(int(add_months(to_days(["2023-11-30"]), 3)[0]), "D")) == "2024-02-29"
