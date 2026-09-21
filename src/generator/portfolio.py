"""Stage 2a: synthetic loan portfolio (contract data)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.common.calendar import to_days, from_days, month_index, month_start

BRANCHES = [f"BR{n:03d}" for n in range(1, 41)]
REGIONS = ["North", "South", "East", "West"]


def product_master_table(cfg: dict) -> pd.DataFrame:
    rows = []
    for code, p in cfg["products"].items():
        sh = p["spread_history"]
        rows.append({
            "product_code": code, "name": p["name"], "rate_type": p["rate_type"], "benchmark": p["benchmark"],
            "current_spread_pct": sh[-1]["spread_pct"] if sh else None,
            "spread_history": "; ".join(f"{x['effective_from']}:{x['spread_pct']}" for x in sh) or None,
            "fixed_rate_pct": p["fixed_rate_pct"], "day_count_convention": p["day_count_convention"],
            "reset_frequency_months": p["reset_frequency_months"], "repayment_type": p["repayment_type"],
            "moratorium_allowed": p["moratorium_allowed"],
            "penal_charge_rule": f"{p['penal_charge_rule']['type']}: INR {p['penal_charge_rule']['amount_inr']}",
            "rounding_rule": f"{p['rounding_rule']['decimals']}dp {p['rounding_rule']['method']} {p['rounding_rule']['frequency']}",
        })
    return pd.DataFrame(rows)


def generate_loans(cfg: dict, rng: np.random.Generator) -> pd.DataFrame:
    n = cfg["portfolio"]["n_loans"]
    obs = cfg["observation"]
    d0, d1 = to_days([str(obs["disbursal_start"]), str(obs["disbursal_end"])])
    codes = list(cfg["products"])
    shares = np.array([cfg["products"][c]["generation"]["share"] for c in codes])
    counts = np.floor(shares / shares.sum() * n).astype(int)
    counts[0] += n - counts.sum()
    frames = []
    for code, cnt in zip(codes, counts):
        g = cfg["products"][code]["generation"]
        principal = np.exp(rng.normal(np.log(g["principal_median_inr"]), g["principal_sigma"], cnt))
        principal = np.round(np.clip(principal, g["principal_min_inr"], g["principal_max_inr"]), -3)
        lo, hi = g["risk_premium_pct"]
        prem = np.round(rng.uniform(lo, hi, cnt) / 0.05) * 0.05
        mor = np.zeros(cnt, dtype=int)
        if cfg["products"][code]["moratorium_allowed"]:
            has = rng.random(cnt) < g["moratorium_share"]
            mlo, mhi = g["moratorium_months"]
            mor[has] = rng.integers(mlo, mhi + 1, has.sum())
        frames.append(pd.DataFrame({
            "product_code": code,
            "disbursal_days": rng.integers(d0, d1 + 1, cnt),
            "principal_inr": principal,
            "tenure_months": rng.choice(g["tenure_months"], cnt),
            "risk_premium_pct": np.round(prem, 2),
            "moratorium_months": mor,
        }))
    df = pd.concat(frames, ignore_index=True).sort_values(["disbursal_days", "product_code"], kind="stable")
    df = df.reset_index(drop=True)
    df.insert(0, "loan_id", [f"LN{k:07d}" for k in range(1, len(df) + 1)])
    df["disbursal_date"] = from_days(df["disbursal_days"].to_numpy()).astype(str)
    dm = month_index(df["disbursal_days"].to_numpy())
    last_m = dm + df["moratorium_months"].to_numpy() + df["tenure_months"].to_numpy()
    emi = df["product_code"].map(lambda c: cfg["products"][c]["repayment_type"] == "emi").to_numpy()
    df["first_due_date"] = from_days(month_start(np.where(emi, dm + df["moratorium_months"] + 1, last_m) + 1) - 1).astype(str)
    df["maturity_date"] = from_days(month_start(last_m + 1) - 1).astype(str)
    df["branch_code"] = rng.choice(BRANCHES, len(df))
    df["region"] = df["branch_code"].map(lambda b: REGIONS[int(b[2:]) % 4])
    return df.drop(columns="disbursal_days")
