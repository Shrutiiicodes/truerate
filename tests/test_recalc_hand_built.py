"""Small hand-built loans recalculated by the audit engine and checked by hand."""
import numpy as np
import pandas as pd
import pytest
from src.common.config import load_yaml
from src.common.calendar import month_index, to_days
from src.generator.reference import build_benchmarks
from src.audit_engine.population import build_population
from src.audit_engine.recalc import recalculate, Hypothesis


def make(loans, tx):
    loans = pd.DataFrame(loans)
    tx = pd.DataFrame(tx, columns=["loan_id", "txn_date", "txn_type", "amount_inr"])
    return build_population(loans, tx, build_benchmarks(), load_yaml("products.yaml"))


def m(p):
    return int(month_index(to_days([p + "-01"]))[0])


def test_personal_loan_first_two_periods_by_hand():
    pop = make([{"loan_id": "T1", "product_code": "PL-FIX", "disbursal_date": "2023-01-10", "principal_inr": 100000.0,
                 "tenure_months": 12, "risk_premium_pct": 0.25, "moratorium_months": 0}],
               [("T1", "2023-01-10", "DISBURSAL", 100000.0), ("T1", "2023-02-28", "EMI", 8838.0)])
    r = recalculate(pop)
    # rate = 10.75 card + 0.25 premium = 11.00%, ACT/365F
    jan = 100000 * 0.11 * 22 / 365          # 10-Jan .. 31-Jan inclusive = 22 days -> 663.01
    feb = 100000 * 0.11 * 28 / 365          # 843.84
    assert r["interest"][0, m("2023-01")] == pytest.approx(round(jan, 2))
    assert r["interest"][0, m("2023-02")] == pytest.approx(round(feb, 2))
    # EMI 8,838 pays the two months' interest first, remainder reduces principal
    assert r["closing_principal"][0, m("2023-02")] == pytest.approx(100000 - (8838 - 663.01 - 843.84), abs=0.005)


def test_floating_reset_exactly_on_repo_change_date_splits_the_period():
    # HL-FLT, quarterly reset from 08-Mar-2022 -> first reset 08-Jun-2022 = MPC date (repo 4.40 -> 4.90)
    pop = make([{"loan_id": "T2", "product_code": "HL-FLT", "disbursal_date": "2022-03-08", "principal_inr": 1_000_000.0,
                 "tenure_months": 240, "risk_premium_pct": 0.0, "moratorium_months": 0}],
               [("T2", "2022-03-08", "DISBURSAL", 1_000_000.0)])
    r = recalculate(pop)
    # rate before: repo on 08-Mar-2022 (4.00) + 2.75 = 6.75; after: 4.90 + 2.75 = 7.65 from 08-Jun
    # June has no payments here, so principal is unchanged at 1,000,000
    june = 1_000_000 * (0.0675 * 7 + 0.0765 * 23) / 365
    assert r["interest"][0, m("2022-06")] == pytest.approx(round(june, 2))
    # May-2022 repo hike (04-May) does NOT affect the loan before its reset date
    assert r["interest"][0, m("2022-05")] == pytest.approx(round(1_000_000 * 0.0675 * 31 / 365, 2))


def test_actact_leap_year_and_365_hypothesis():
    pop = make([{"loan_id": "T3", "product_code": "MSME-FLT", "disbursal_date": "2024-01-15", "principal_inr": 500000.0,
                 "tenure_months": 36, "risk_premium_pct": 0.0, "moratorium_months": 0}],
               [("T3", "2024-01-15", "DISBURSAL", 500000.0)])
    feb = 500000 * (0.065 + 0.035) * 29 / 366          # repo 6.50 + 3.50 spread, 29 days / 366
    assert recalculate(pop)["interest"][0, m("2024-02")] == pytest.approx(round(feb, 2))
    wrong = recalculate(pop, Hypothesis(leap_365=True))["interest"][0, m("2024-02")]
    assert wrong == pytest.approx(round(500000 * 0.10 * 29 / 365, 2))


def test_moratorium_interest_is_simple_not_compounded():
    pop = make([{"loan_id": "T4", "product_code": "HL-FLT", "disbursal_date": "2023-04-01", "principal_inr": 2_000_000.0,
                 "tenure_months": 240, "risk_premium_pct": 0.0, "moratorium_months": 3}],
               [("T4", "2023-04-01", "DISBURSAL", 2_000_000.0)])
    r = recalculate(pop)
    for p in ["2023-05", "2023-06", "2023-07"]:              # principal never grows during moratorium
        assert r["closing_principal"][0, m(p)] == pytest.approx(2_000_000.0)
    c = recalculate(pop, Hypothesis(compound_moratorium=True))
    assert c["closing_principal"][0, m("2023-07")] > 2_000_000.0


def test_penal_charge_is_fixed_fee_not_capitalised():
    pop = make([{"loan_id": "T5", "product_code": "PL-FIX", "disbursal_date": "2024-05-10", "principal_inr": 200000.0,
                 "tenure_months": 24, "risk_premium_pct": 0.0, "moratorium_months": 0}],
               [("T5", "2024-05-10", "DISBURSAL", 200000.0), ("T5", "2024-08-31", "EMI_BOUNCED", 0.0)])
    r = recalculate(pop)
    assert r["penal_charge"][0, m("2024-08")] == 500.0                  # product rule: INR 500 per bounce
    assert r["closing_balance"][0, m("2024-08")] - r["closing_principal"][0, m("2024-08")] >= 500.0
    cap = recalculate(pop, Hypothesis(penal_mode="capitalise"))
    assert cap["closing_principal"][0, m("2024-08")] == pytest.approx(r["closing_principal"][0, m("2024-08")] + 500.0)


def test_accrual_stops_on_closure_value_date():
    pop = make([{"loan_id": "T6", "product_code": "GL-FIX", "disbursal_date": "2024-03-05", "principal_inr": 100000.0,
                 "tenure_months": 12, "risk_premium_pct": 0.0, "moratorium_months": 0}],
               [("T6", "2024-03-05", "DISBURSAL", 100000.0), ("T6", "2024-04-11", "FULL_PREPAYMENT", 101000.0)])
    r = recalculate(pop)
    assert r["interest"][0, m("2024-04")] == pytest.approx(round(100000 * 0.0925 * 10 / 365, 2))   # 1..10 April
    assert np.isnan(r["interest"][0, m("2024-05")])                                               # no row after closure
