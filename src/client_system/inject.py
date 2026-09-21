"""Fault selection driven by config/injection.yaml. Client-side only."""
from __future__ import annotations
import json
import numpy as np
import pandas as pd
from src.common.calendar import to_days, month_index
from .book import LoanBook
from .engine import Faults, N_MONTHS


def eligibility(rule, book: LoanBook, tx: pd.DataFrame, cfg_products: dict, ctrl_params: dict) -> np.ndarray:
    n = book.n
    close_m = book.last_m.copy()
    fp = tx[tx.txn_type == "FULL_PREPAYMENT"].set_index("loan_id")["txn_date"]
    fp_days = pd.Series(book.loan_id).map(fp)
    has_fp = fp_days.notna().to_numpy()
    fp_m = np.where(has_fp, month_index(to_days(fp_days.fillna("2100-01-01").astype(str))), 10_000)
    close_m = np.minimum(close_m, fp_m)
    if rule == "all":
        return np.ones(n, bool)
    if isinstance(rule, dict) and "product" in rule:
        return book.product == rule["product"]
    if rule == "floating_with_reset":
        return book.floating & (book.disb_m + book.freq < np.minimum(close_m, N_MONTHS))
    if rule == "has_moratorium":
        return book.mor > 0
    if rule == "missed_after_switchover":
        b = tx[tx.txn_type == "EMI_BOUNCED"][["loan_id", "txn_date"]].copy()
        b["m"] = month_index(to_days(b["txn_date"].astype(str)))
        sw = pd.Series(book.switch_m, index=book.loan_id)
        ok = b[b["m"].to_numpy() >= sw.loc[b["loan_id"]].to_numpy()]["loan_id"].unique()
        return np.isin(book.loan_id, ok)
    if rule == "stale_spread_candidates":
        change = to_days([str(ctrl_params["change_date"])])[0]
        cm = month_index(np.array([change]))[0]
        return (book.product == ctrl_params["product"]) & (book.disb < change) & (close_m >= cm + 3)
    if rule == "full_prepaid":
        return has_fp & (fp_m < N_MONTHS)
    if rule == "actact_active_in_leap_year":
        return (book.conv == 1) & (book.disb_m <= 47) & (close_m >= 36)
    raise ValueError(rule)


def select_faults(book: LoanBook, tx: pd.DataFrame, cfg: dict, inj: dict):
    rng = np.random.default_rng(inj["seed"])
    n = book.n
    f = Faults.none(n)
    f.penal_rate_pct = float(inj["controls"]["C-05"]["params"]["penal_rate_pct"])
    f.daily_decimals = int(inj["controls"]["C-06"]["params"]["daily_decimals"])
    f.stale_cutoff = int(to_days([str(inj["controls"]["C-07"]["params"]["change_date"])])[0])
    taken = np.zeros(n, bool)
    labels = []
    elig = {c: eligibility(v["eligible"], book, tx, cfg["products"], v["params"]) for c, v in inj["controls"].items()}

    def apply(c, idx):
        spec = inj["controls"][c]
        for j in idx:
            params = {}
            if c == "C-01":
                params["rate_offset_pct"] = float(rng.choice(spec["params"]["rate_offset_pct_choices"]))
                f.rate_offset[j] = params["rate_offset_pct"]
            elif c == "C-02": f.reset_lag[j] = True; params["lag_cycles"] = 1
            elif c == "C-03": f.dc30360[j] = True; params["convention"] = "30E/360"
            elif c == "C-04": f.mor_compound[j] = True
            elif c == "C-05":
                mode = str(rng.choice(spec["params"]["modes"]))
                f.penal_mode[j] = 1 if mode == "capitalise" else 2
                params["mode"] = mode
                if mode == "add_to_rate": params["penal_rate_pct"] = f.penal_rate_pct
            elif c == "C-06": f.daily_round[j] = True; params["daily_decimals"] = f.daily_decimals
            elif c == "C-07": f.stale_spread[j] = True; params["change_date"] = str(spec["params"]["change_date"])
            elif c == "C-08": f.accrual_after_close[j] = True
            elif c == "C-09": f.leap365[j] = True
            labels.append({"loan_id": book.loan_id[j], "control_id": c, "fault_type": spec["fault"],
                           "params": json.dumps(params)})

    for c, spec in inj["controls"].items():                 # single-fault pass (disjoint)
        pool = np.nonzero(elig[c] & ~taken)[0]
        pick = rng.choice(pool, size=min(spec["n_loans"], len(pool)), replace=False)
        taken[pick] = True
        apply(c, pick)
    first = pd.DataFrame(labels)
    ctrl_of = dict(zip(first["loan_id"], first["control_id"]))
    pos = {lid: k for k, lid in enumerate(book.loan_id)}
    added, tries = 0, 0
    controls = list(inj["controls"])
    while added < inj["double_faults"] and tries < 10_000:   # second fault on already-faulty loans
        tries += 1
        c2 = str(rng.choice(controls))
        cand = [pos[l] for l, c in ctrl_of.items() if c != c2 and elig[c2][pos[l]]]
        if not cand:
            continue
        j = int(rng.choice(cand))
        ctrl_of.pop(book.loan_id[j])
        apply(c2, [j])
        added += 1
    lab = pd.DataFrame(labels)
    lab["n_faults_on_loan"] = lab.groupby("loan_id")["control_id"].transform("size")
    return f, lab
