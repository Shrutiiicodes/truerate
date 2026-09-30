"""Differential test: the vectorised recalculation vs a deliberately naive reference.

The reference accrues day by day in Decimal using only the stdlib (datetime,
calendar, decimal) and the documented business rules. It shares no code with
src/common, so a bug in the shared primitives (day-count, rounding, rate lookup)
that the auditor and the client both inherit would show up here as a mismatch.
"""
import bisect
import calendar
import datetime as dt
from collections import defaultdict
from decimal import Decimal as D, ROUND_HALF_UP
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.audit_engine.population import build_population, METRICS
from src.audit_engine.recalc import recalculate

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "data" / "generated"
START, N_MONTHS, CENT = dt.date(2021, 1, 1), 54, D("0.01")
PAYMENTS = {"EMI", "EMI_CATCH_UP", "FINAL_SETTLEMENT"}


def dec(x):
    return D(repr(float(x)))


def date(x):
    return x if isinstance(x, dt.date) else dt.date.fromisoformat(str(x))


def add_months(d, k):
    y, m = divmod(d.month - 1 + k, 12)
    y, m = d.year + y, m + 1
    return dt.date(y, m, min(d.day, calendar.monthrange(y, m)[1]))


def month_of(d):
    return (d.year - START.year) * 12 + d.month - 1


def step(points):
    """Piecewise-constant lookup: the value in force ON date d."""
    pts = sorted(points)
    dates = [p[0] for p in pts]
    return lambda d: pts[bisect.bisect_right(dates, d) - 1][1]


def reference_ledger(loan, txs, prod, bench):
    disb = date(loan["disbursal_date"])
    disb_m = month_of(disb)
    maturity_m = disb_m + loan["moratorium_months"] + loan["tenure_months"]
    prem = dec(loan["risk_premium_pct"])
    floating = prod["rate_type"] == "floating"
    spread = step([(date(s["effective_from"]), dec(s["spread_pct"])) for s in prod["spread_history"]])
    rate_on = (lambda d: bench[prod["benchmark"]](d) + spread(d) + prem) if floating \
        else (lambda d: dec(prod["fixed_rate_pct"]) + prem)
    actact = prod["day_count_convention"] == "ACT/ACT"
    cycle = prod["reset_frequency_months"]
    fee = dec(prod["penal_charge_rule"]["amount_inr"])

    pay, bounced, prepay, close = defaultdict(D), set(), {}, None
    for t in txs.itertuples():
        d = date(t.txn_date)
        if t.txn_type in PAYMENTS:
            pay[month_of(d)] += dec(t.amount_inr)
        elif t.txn_type == "EMI_BOUNCED":
            bounced.add(month_of(d))
        elif t.txn_type == "PART_PREPAYMENT":
            prepay[month_of(d)] = (d, dec(t.amount_inr))
        elif t.txn_type == "FULL_PREPAYMENT":
            close = (d, dec(t.amount_inr))

    principal, arrears, penal_due, rate = dec(loan["principal_inr"]), D(0), D(0), rate_on(disb)
    out = {}
    for m in range(disb_m, N_MONTHS):
        p_start, p_end = add_months(START, m), add_months(START, m + 1)
        start = max(p_start, disb)
        closes = close is not None and p_start <= close[0] < p_end
        end = close[0] if closes else p_end
        age = m - disb_m
        reset_day = add_months(disb, age) if floating and cycle and age > 0 and age % cycle == 0 else None
        if reset_day is not None and reset_day >= end:
            reset_day = None
        new_rate = rate_on(reset_day) if reset_day else rate
        pp_day, pp_amt = prepay.get(m, (None, D(0)))
        if pp_day is not None and not (start <= pp_day < end):
            pp_day, pp_amt = None, D(0)

        acc, d = D(0), start
        while d < end:                                   # one day at a time, no segmenting
            bal = principal - (pp_amt if pp_day and d >= pp_day else 0)
            r = new_rate if reset_day and d >= reset_day else rate
            acc += bal * r / 100 / (366 if actact and calendar.isleap(d.year) else 365)
            d += dt.timedelta(days=1)
        interest = acc.quantize(CENT, rounding=ROUND_HALF_UP)
        charge = fee if m in bounced else D(0)

        principal -= pp_amt
        arrears += interest
        penal_due += charge
        rate = new_rate
        cash = pay[m] + (close[1] if closes else 0)      # waterfall: penal -> interest -> principal
        x = min(cash, max(penal_due, D(0))); penal_due -= x; cash -= x
        x = min(cash, max(arrears, D(0))); arrears -= x; cash -= x
        principal -= cash
        out[m] = {"interest": interest, "penal_charge": charge, "closing_principal": principal,
                  "closing_balance": principal + arrears + penal_due}
        if closes or m == maturity_m:
            break
    return out


@pytest.fixture(scope="module")
def sample():
    if not (GEN / "loans.parquet").exists() or not (GEN / "transactions.parquet").exists():
        pytest.skip("generated data missing - run `python run_all.py`")
    loans = pd.read_parquet(GEN / "loans.parquet")
    tx = pd.read_parquet(GEN / "transactions.parquet")
    rng = np.random.default_rng(0)
    pick = lambda ids, k: list(rng.choice(sorted(ids), size=min(k, len(ids)), replace=False))
    ids = []
    for _, g in loans.groupby("product_code"):                     # every product and day-count convention
        ids += pick(g.loan_id, 15)
    for kind in ["PART_PREPAYMENT", "FULL_PREPAYMENT", "EMI_BOUNCED", "EMI_CATCH_UP"]:
        ids += pick(set(tx.loc[tx.txn_type == kind, "loan_id"]), 15)
    ids += pick(loans.loc[loans.moratorium_months > 0, "loan_id"], 15)
    loans = loans[loans.loan_id.isin(set(ids))].reset_index(drop=True)
    tx = tx[tx.loan_id.isin(set(ids))]
    bench = pd.read_csv(ROOT / "data" / "reference" / "benchmark_rates.csv")
    master = yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))
    return loans, tx, bench, master


def test_vectorised_recalc_matches_naive_daily_decimal_reference(sample):
    loans, tx, bench, master = sample
    exp = recalculate(build_population(loans, tx, bench, master))
    curves = {name: step([(date(r.effective_date), dec(r.rate_pct)) for r in g.itertuples()])
              for name, g in bench.groupby("benchmark")}
    by_loan = dict(list(tx.groupby("loan_id")))
    bad = []
    for i, loan in enumerate(loans.to_dict("records")):
        ref = reference_ledger(loan, by_loan[loan["loan_id"]], master["products"][loan["product_code"]], curves)
        periods = set(np.nonzero(~np.isnan(exp["interest"][i]))[0].tolist())
        assert periods == set(ref), f"{loan['loan_id']}: period coverage differs"
        for m, row in ref.items():
            for c in METRICS:
                # 2 paise: allows one half-up tie resolved differently in float vs Decimal
                if abs(float(row[c]) - exp[c][i, m]) > 0.02:
                    bad.append((loan["loan_id"], m, c, float(row[c]), round(float(exp[c][i, m]), 2)))
    assert len(loans) >= 80
    assert not bad, f"{len(bad)} mismatches, first: {bad[:5]}"
