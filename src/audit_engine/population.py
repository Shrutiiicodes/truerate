"""Auditor-visible inputs only: product master, benchmark rates, loan contracts,
transactions and the client's interest ledger. Builds dense per-loan x per-month
arrays so the full population can be recalculated with vectorised arithmetic."""
from __future__ import annotations
from dataclasses import dataclass, fields
import numpy as np
import pandas as pd
from src.common.config import load_yaml
from src.common.io import load_table
from src.common.calendar import to_days, month_index
from src.common.daycount import CODE
from src.common.rates import load_benchmark_curves, spread_curve

N_MONTHS = 54
METRICS = ["interest", "penal_charge", "closing_principal", "closing_balance"]


@dataclass
class Population:
    loan_id: np.ndarray
    product: np.ndarray
    p_idx: np.ndarray
    disb: np.ndarray
    disb_m: np.ndarray
    principal: np.ndarray
    tenure: np.ndarray
    mor: np.ndarray
    maturity_m: np.ndarray
    is_emi: np.ndarray
    dc: np.ndarray
    reset_months: np.ndarray
    floating: np.ndarray
    bm: np.ndarray                  # benchmark name per loan ('' for fixed)
    card_rate: np.ndarray
    premium: np.ndarray
    penal_fee: np.ndarray
    regime_m: np.ndarray            # first month under the 2024 penal-charge regime
    stale_cutoff: np.ndarray        # latest product-master spread change (int days), or 0
    # transaction facts (dense)
    pay: np.ndarray
    bounced: np.ndarray
    pp_day: np.ndarray
    pp_amt: np.ndarray
    close_day: np.ndarray           # full prepayment date or -1
    close_amt: np.ndarray
    # reference curves
    benchmarks: dict
    spreads: dict

    def take(self, idx):
        return Population(**{f.name: (getattr(self, f.name)[idx] if isinstance(getattr(self, f.name), np.ndarray)
                                      else getattr(self, f.name)) for f in fields(self)})

    @property
    def size(self):
        return len(self.loan_id)


def load_population() -> tuple[Population, pd.DataFrame, dict]:
    master = load_yaml("products.yaml")
    loans = load_table("loans")
    tx = load_table("transactions")
    bench = load_table("benchmark_rates")
    ledger = load_table("system_interest_ledger")
    return build_population(loans, tx, bench, master), ledger, {"loans": loans, "transactions": tx, "master": master}


def build_population(loans, tx, bench, master) -> Population:
    prods = master["products"]
    names = list(prods)
    p_idx = loans["product_code"].map({p: k for k, p in enumerate(names)}).to_numpy()
    attr = lambda fn: np.array([fn(prods[p]) for p in names])[p_idx]
    disb = to_days(loans["disbursal_date"].astype(str))
    dm = month_index(disb)
    ten = loans["tenure_months"].to_numpy()
    mor = loans["moratorium_months"].to_numpy()
    reg = master["penal_regime"]
    fresh = to_days([str(reg["fresh_loans_from"])])[0]
    backstop = month_index(to_days([str(reg["existing_loans_switchover"])]))[0]
    changes = attr(lambda p: to_days([str(p["spread_history"][-1]["effective_from"])])[0]
                   if len(p["spread_history"]) > 1 else 0)
    n = len(loans)
    key = pd.Index(loans["loan_id"].to_numpy())
    t = tx.assign(i=key.get_indexer(tx["loan_id"]), d=to_days(tx["txn_date"].astype(str)))
    t["m"] = month_index(t["d"].to_numpy())
    pay = np.zeros((n, N_MONTHS)); bounced = np.zeros((n, N_MONTHS), bool)
    pp_day = np.full((n, N_MONTHS), -1, np.int64); pp_amt = np.zeros((n, N_MONTHS))
    close_day = np.full(n, -1, np.int64); close_amt = np.zeros(n)
    sel = t[t.txn_type.isin(["EMI", "EMI_CATCH_UP", "FINAL_SETTLEMENT"])]
    np.add.at(pay, (sel.i.to_numpy(), sel.m.to_numpy()), sel.amount_inr.to_numpy())
    sel = t[t.txn_type == "EMI_BOUNCED"]; bounced[sel.i, sel.m] = True
    sel = t[t.txn_type == "PART_PREPAYMENT"]; pp_day[sel.i, sel.m] = sel.d; pp_amt[sel.i, sel.m] = sel.amount_inr
    sel = t[t.txn_type == "FULL_PREPAYMENT"]; close_day[sel.i] = sel.d; close_amt[sel.i] = sel.amount_inr
    return Population(
        loan_id=loans["loan_id"].to_numpy(), product=loans["product_code"].to_numpy(), p_idx=p_idx,
        disb=disb, disb_m=dm, principal=loans["principal_inr"].to_numpy(float), tenure=ten, mor=mor,
        maturity_m=dm + mor + ten, is_emi=attr(lambda p: p["repayment_type"] == "emi"),
        dc=attr(lambda p: CODE[p["day_count_convention"]]), reset_months=attr(lambda p: p["reset_frequency_months"]),
        floating=attr(lambda p: p["rate_type"] == "floating"),
        bm=attr(lambda p: p["benchmark"] if p["rate_type"] == "floating" else ""),
        card_rate=attr(lambda p: p["fixed_rate_pct"] or 0.0), premium=loans["risk_premium_pct"].to_numpy(float),
        penal_fee=attr(lambda p: float(p["penal_charge_rule"]["amount_inr"])),
        regime_m=np.where(disb >= fresh, dm, backstop), stale_cutoff=changes,
        pay=pay, bounced=bounced, pp_day=pp_day, pp_amt=pp_amt, close_day=close_day, close_amt=close_amt,
        benchmarks=load_benchmark_curves(bench), spreads={k: spread_curve(prods[p]["spread_history"]) for k, p in enumerate(names)},
    )


def system_dense(pop: Population, ledger: pd.DataFrame) -> dict:
    """Client ledger pivoted to (loan x month) arrays aligned to the population."""
    i_all = pd.Index(pop.loan_id).get_indexer(ledger["loan_id"])
    known = i_all >= 0
    lg = ledger[known]
    i = i_all[known]
    per = lg["period"].astype(str)
    m = (per.str[:4].astype(int).to_numpy() - 2021) * 12 + per.str[5:7].astype(int).to_numpy() - 1
    out = {}
    for c in METRICS:
        a = np.full((pop.size, N_MONTHS), np.nan)
        a[i, m] = lg[c].to_numpy()
        out[c] = a
    out["_unknown_loan_rows"] = int((~known).sum())
    return out
