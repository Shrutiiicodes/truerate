"""Build per-loan attribute arrays from the loans table + product master
(client-side copy; the audit engine builds its own independently)."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import pandas as pd
from src.common.calendar import to_days, month_index
from src.common.daycount import CODE
from src.common.rates import load_benchmark_curves, spread_curve

BENCH_CODE = {"NONE": 0, "REPO": 1, "MCLR_1Y": 2}


@dataclass
class LoanBook:
    loan_id: np.ndarray
    product: np.ndarray          # product code string
    prod_idx: np.ndarray         # int index into product list
    disb: np.ndarray             # int days
    disb_m: np.ndarray
    principal: np.ndarray
    tenure: np.ndarray
    mor: np.ndarray
    first_emi_m: np.ndarray
    last_m: np.ndarray           # month of final settlement (maturity)
    is_emi: np.ndarray
    conv: np.ndarray             # day-count code
    freq: np.ndarray             # reset frequency months (0 = fixed)
    floating: np.ndarray
    bench: np.ndarray            # benchmark code
    fixed_base: np.ndarray
    premium: np.ndarray
    penal_amt: np.ndarray
    switch_m: np.ndarray         # first month the new penal-charge regime applies
    bench_curves: dict
    spread_curves: dict          # prod_idx -> StepCurve | None

    @property
    def n(self):
        return len(self.loan_id)

    def subset(self, idx):
        kw = {k: (v[idx] if isinstance(v, np.ndarray) else v) for k, v in self.__dict__.items()}
        return LoanBook(**kw)


def build_book(loans: pd.DataFrame, cfg: dict, benchmarks: pd.DataFrame) -> LoanBook:
    prods = list(cfg["products"].keys())
    pidx = loans["product_code"].map({p: i for i, p in enumerate(prods)}).to_numpy()
    P = [cfg["products"][p] for p in prods]
    get = lambda f: np.array([f(P[i]) for i in range(len(P))])[pidx]
    disb = to_days(loans["disbursal_date"].astype(str))
    disb_m = month_index(disb)
    tenure = loans["tenure_months"].to_numpy()
    mor = loans["moratorium_months"].to_numpy()
    is_emi = get(lambda p: p["repayment_type"] == "emi")
    reg = cfg["penal_regime"]
    fresh = to_days([str(reg["fresh_loans_from"])])[0]
    switch_all = month_index(to_days([str(reg["existing_loans_switchover"])]))[0]
    switch_m = np.where(disb >= fresh, disb_m, switch_all)
    return LoanBook(
        loan_id=loans["loan_id"].to_numpy(), product=loans["product_code"].to_numpy(), prod_idx=pidx,
        disb=disb, disb_m=disb_m, principal=loans["principal_inr"].to_numpy(float), tenure=tenure, mor=mor,
        first_emi_m=disb_m + mor + 1, last_m=disb_m + mor + tenure, is_emi=is_emi,
        conv=get(lambda p: CODE[p["day_count_convention"]]), freq=get(lambda p: p["reset_frequency_months"]),
        floating=get(lambda p: p["rate_type"] == "floating"), bench=get(lambda p: BENCH_CODE[p["benchmark"]]),
        fixed_base=get(lambda p: p["fixed_rate_pct"] or 0.0), premium=loans["risk_premium_pct"].to_numpy(float),
        penal_amt=get(lambda p: float(p["penal_charge_rule"]["amount_inr"])), switch_m=switch_m,
        bench_curves={BENCH_CODE[k]: v for k, v in load_benchmark_curves(benchmarks).items()},
        spread_curves={i: spread_curve(P[i]["spread_history"]) for i in range(len(P))},
    )
