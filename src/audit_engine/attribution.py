"""Stage 5: root-cause attribution by hypothesis testing.

Each candidate configuration error is re-performed on the exception loans; a
hypothesis 'explains' a loan when its recalculated ledger agrees with the system
ledger within tolerance for EVERY period and metric. Pairs are tried for loans
no single hypothesis explains. The wrong-spread hypothesis (C-01) does not use a
fixed grid: the implied rate offset is solved from the data
(difference / interest-per-1%-of-rate), rounded to 5 bps, then re-tested.
"""
from __future__ import annotations
import itertools
import numpy as np
import pandas as pd
from .recalc import Hypothesis, recalculate, BASELINE
from .compare import loans_matching

CONTROL_OF = {"C-01": "Rate application", "C-02": "Reset timing", "C-03": "Day-count", "C-04": "Moratorium",
              "C-05": "Penal charges", "C-06": "Rounding", "C-07": "Product master change (ITGC)",
              "C-08": "Accrual stop", "C-09": "Leap year"}


def candidate_hypotheses(cfg_attr: dict) -> list[Hypothesis]:
    hs = [Hypothesis("C-01 wrong spread (implied)", ("C-01",), rate_offset=np.nan),
          Hypothesis("C-02 reset one cycle late", ("C-02",), reset_lag=True),
          Hypothesis("C-03 30E/360 day-count", ("C-03",), thirty_360=True),
          Hypothesis("C-04 moratorium interest compounded", ("C-04",), compound_moratorium=True),
          Hypothesis("C-05 penal charge capitalised", ("C-05",), penal_mode="capitalise")]
    for pr in cfg_attr["penal_rate_pct_candidates"]:
        hs.append(Hypothesis(f"C-05 penal interest +{pr}% on rate", ("C-05",), penal_mode="add_to_rate", penal_rate=pr))
    for dp in cfg_attr["daily_rounding_decimals"]:
        hs.append(Hypothesis(f"C-06 daily rounding to {dp}dp", ("C-06",), daily_decimals=dp))
    hs += [Hypothesis("C-07 stale pre-change spread", ("C-07",), stale_spread=True),
           Hypothesis("C-08 accrual after closure", ("C-08",), accrue_after_close=True),
           Hypothesis("C-09 365-day basis in leap year", ("C-09",), leap_365=True)]
    return hs


def implied_offset(sys: dict, ref: dict, abs_tol: float, step: float) -> np.ndarray:
    """Per-loan rate offset implied by the FIRST period whose interest differs from
    the reference by more than the tolerance. Opening balances still agree in that
    period, so difference / (interest per 1% of rate) isolates the rate error;
    later periods are contaminated by the balance divergence the error creates."""
    diff = np.nan_to_num(sys["interest"] - ref["interest"])
    base = np.nan_to_num(ref["rate_base"])
    ok = (base > 0) & (np.abs(diff) > abs_tol)
    first = ok.argmax(axis=1)
    rows = np.arange(diff.shape[0])
    est = np.where(ok.any(axis=1), diff[rows, first] / np.where(base[rows, first] > 0, base[rows, first], 1.0), 0.0)
    return np.round(np.round(est / step) * step, 4)


def attribute(pop, sys: dict, abs_tol: float, rel_tol: float, cfg_attr: dict):
    """pop / sys are already restricted to exception loans."""
    step = cfg_attr["rate_offset_round_pct"]
    base = recalculate(pop, BASELINE)
    singles = candidate_hypotheses(cfg_attr)
    n = pop.size
    matches = {}         # hypothesis name -> bool array
    ledgers = {}
    resolved = {}
    for h in singles:
        if "C-01" in h.controls:
            off = implied_offset(sys, base, abs_tol, step)
            h2 = Hypothesis(h.name, h.controls, rate_offset=off)
            res = recalculate(pop, h2)
            ok = loans_matching(res, sys, abs_tol, rel_tol) & (off != 0)
        else:
            h2 = h
            res = recalculate(pop, h)
            ok = loans_matching(res, sys, abs_tol, rel_tol)
        matches[h.name] = ok; ledgers[h.name] = res; resolved[h.name] = h2

    single_ctrl = _controls_matched(matches, singles, n)
    unexplained = np.array([len(s) == 0 for s in single_ctrl])
    pair_matches = {}
    if cfg_attr.get("test_pairs", True) and unexplained.any():
        idx = np.nonzero(unexplained)[0]
        sub, subsys = pop.take(idx), {k: v[idx] for k, v in sys.items() if isinstance(v, np.ndarray)}
        for h1, h2 in itertools.combinations(singles, 2):
            if set(h1.controls) & set(h2.controls):
                continue
            if "C-01" in h2.controls:
                h1, h2 = h2, h1
            if "C-01" in h1.controls:          # solve offset on top of the other hypothesis
                ref = {k: v[idx] for k, v in ledgers[h2.name].items()}
                off = implied_offset(subsys, ref, abs_tol, step)
                combo = h2 + Hypothesis(h1.name, h1.controls, rate_offset=off)
                valid = off != 0
            else:
                combo = resolved[h1.name] + resolved[h2.name]
                valid = np.ones(len(idx), bool)
            ok = loans_matching(recalculate(sub, combo), subsys, abs_tol, rel_tol) & valid
            full = np.zeros(n, bool); full[idx] = ok
            pair_matches[f"{h1.name} + {h2.name}"] = (full, tuple(sorted(set(h1.controls + h2.controls))))

    rows = []
    for j in range(n):
        s_names = [h.name for h in singles if matches[h.name][j]]
        s_ctrls = sorted({c for h in singles if matches[h.name][j] for c in h.controls})
        if s_ctrls:
            status = "Attributed" if len(s_ctrls) == 1 else "Ambiguous"
            names, ctrls = s_names, ["+".join(s_ctrls)] if len(s_ctrls) == 1 else s_ctrls
        else:
            p_names = [k for k, (ok, _) in pair_matches.items() if ok[j]]
            p_sets = sorted({"+".join(cs) for k, (ok, cs) in pair_matches.items() if ok[j]})
            if p_sets:
                status = "Attributed" if len(p_sets) == 1 else "Ambiguous"
                names, ctrls = p_names, p_sets
            else:
                status, names, ctrls = "Unexplained", [], []
        rows.append({"loan_id": pop.loan_id[j], "product_code": pop.product[j], "status": status,
                     "control_ids": " | ".join(ctrls), "matching_hypotheses": " | ".join(names),
                     "implied_rate_offset_pct": float(resolved[singles[0].name].rate_offset[j])
                     if "C-01" in "".join(ctrls) else np.nan})
    att = pd.DataFrame(rows)
    return att, base, ledgers


def _controls_matched(matches, singles, n):
    return [{c for h in singles if matches[h.name][j] for c in h.controls} for j in range(n)]
