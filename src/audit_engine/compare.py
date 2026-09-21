"""Expected vs system comparison with tolerance: |diff| > max(abs_tol, rel_tol x |expected|)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.common.calendar import period_label
from .population import Population, METRICS


def tolerance(expected, abs_tol: float, rel_tol: float):
    return np.maximum(abs_tol, rel_tol * np.abs(np.nan_to_num(expected)))


def breach_mask(exp: dict, sys: dict, abs_tol: float, rel_tol: float, metrics=METRICS):
    """Per metric boolean arrays of breaches, plus completeness breaks (row on one side only)."""
    out = {}
    for c in metrics:
        e, s = exp[c], sys[c]
        both = ~np.isnan(e) & ~np.isnan(s)
        d = np.where(both, s - e, 0.0)
        out[c] = both & (np.abs(d) > tolerance(e, abs_tol, rel_tol))
    out["_missing_in_system"] = ~np.isnan(exp["interest"]) & np.isnan(sys["interest"])
    out["_extra_in_system"] = np.isnan(exp["interest"]) & ~np.isnan(sys["interest"])
    return out


def loans_matching(exp: dict, sys: dict, abs_tol: float, rel_tol: float) -> np.ndarray:
    """True for loans where every period and metric agrees within tolerance."""
    b = breach_mask(exp, sys, abs_tol, rel_tol)
    bad = np.zeros(exp["interest"].shape[0], bool)
    for v in b.values():
        bad |= v.any(axis=1)
    return ~bad


def exceptions_table(pop: Population, exp: dict, sys: dict, abs_tol: float, rel_tol: float) -> pd.DataFrame:
    b = breach_mask(exp, sys, abs_tol, rel_tol)
    frames = []
    for c in METRICS:
        li, mi = np.nonzero(b[c])
        if len(li) == 0:
            continue
        e, s = exp[c][li, mi], sys[c][li, mi]
        frames.append(pd.DataFrame({
            "loan_id": pop.loan_id[li], "product_code": pop.product[li], "period": period_label(mi),
            "metric": c, "expected_inr": np.round(e, 2), "system_inr": np.round(s, 2),
            "difference_inr": np.round(s - e, 2), "tolerance_inr": np.round(tolerance(e, abs_tol, rel_tol), 2)}))
    for key, label in [("_missing_in_system", "row_missing_in_system"), ("_extra_in_system", "row_extra_in_system")]:
        li, mi = np.nonzero(b[key])
        if len(li):
            frames.append(pd.DataFrame({"loan_id": pop.loan_id[li], "product_code": pop.product[li],
                                        "period": period_label(mi), "metric": label}))
    cols = ["loan_id", "product_code", "period", "metric", "expected_inr", "system_inr", "difference_inr", "tolerance_inr"]
    if not frames:
        return pd.DataFrame(columns=cols)
    return pd.concat(frames, ignore_index=True)[cols].sort_values(["loan_id", "period", "metric"]).reset_index(drop=True)
