"""Stage 3 driver: run the client core banking system (with injected faults)
and write `system_interest_ledger`. Ground truth goes ONLY to data/ground_truth/."""
from __future__ import annotations
import time
import numpy as np
import pandas as pd
from src.common.config import load_yaml
from src.common.io import load_table, save_table
from src.common.paths import DATA
from src.common.calendar import month_start, period_label, from_days, to_days, month_index
from .book import build_book
from .engine import Events, run, N_MONTHS
from .inject import select_faults

GROUND_TRUTH = DATA / "ground_truth"
LEDGER_COLS = ["opening_principal", "interest", "penal_charge", "payments", "closing_principal",
               "interest_arrears", "penal_due", "closing_balance"]


def events_from_transactions(book, tx: pd.DataFrame) -> Events:
    """Rebuild dense event arrays from the transaction facts."""
    n, M = book.n, N_MONTHS
    t = tx.copy()
    t["i"] = pd.Index(book.loan_id).get_indexer(t["loan_id"])
    t["d"] = to_days(t["txn_date"].astype(str))
    t["m"] = month_index(t["d"].to_numpy())
    ev = Events(pay=np.zeros((n, M)), missed=np.zeros((n, M), bool), catchup=np.zeros((n, M), bool),
                pp_date=np.full((n, M), -1, np.int64), pp_amt=np.zeros((n, M)), pp_frac=np.zeros((n, M)),
                fp_date=np.full(n, -1, np.int64), fp_amt=np.zeros(n))
    x = t[t.txn_type.isin(["EMI", "EMI_CATCH_UP", "FINAL_SETTLEMENT"])]
    np.add.at(ev.pay, (x.i.to_numpy(), x.m.to_numpy()), x.amount_inr.to_numpy())
    x = t[t.txn_type == "EMI_BOUNCED"]; ev.missed[x.i, x.m] = True
    x = t[t.txn_type == "PART_PREPAYMENT"]; ev.pp_date[x.i, x.m] = x.d; ev.pp_amt[x.i, x.m] = x.amount_inr
    x = t[t.txn_type == "FULL_PREPAYMENT"]; ev.fp_date[x.i] = x.d; ev.fp_amt[x.i] = x.amount_inr
    return ev


def to_long(book, led: dict) -> pd.DataFrame:
    li, mi = np.nonzero(~np.isnan(led["interest"]))
    df = pd.DataFrame({"loan_id": book.loan_id[li], "period": period_label(mi)})
    df["period_start"] = from_days(np.maximum(month_start(mi), book.disb[li])).astype(str)
    for c in LEDGER_COLS:
        df[c] = np.round(led[c][li, mi], 2)
    return df


def main() -> dict:
    t0 = time.time()
    cfg, inj = load_yaml("products.yaml"), load_yaml("injection.yaml")
    loans, tx, bench = load_table("loans"), load_table("transactions"), load_table("benchmark_rates")
    book = build_book(loans, cfg, bench)
    faults, labels = select_faults(book, tx, cfg, inj)
    system = run(book, events_from_transactions(book, tx), faults)
    ledger = to_long(book, system)
    save_table(ledger, "system_interest_ledger")

    # ---- ground truth (client-side knowledge only)
    correct = run(book, events_from_transactions(book, tx), None)
    GROUND_TRUTH.mkdir(parents=True, exist_ok=True)
    diffs = {c: system[c] - correct[c] for c in ["interest", "penal_charge", "closing_principal", "closing_balance"]}
    any_diff = np.zeros_like(system["interest"], dtype=bool)
    for d in diffs.values():
        any_diff |= np.abs(np.nan_to_num(d)) > 0.005
    li, mi = np.nonzero(any_diff)
    aff = pd.DataFrame({"loan_id": book.loan_id[li], "period": period_label(mi)})
    for c, d in diffs.items():
        aff[f"diff_{c}"] = np.round(d[li, mi], 2)
    ctrls = labels.groupby("loan_id")["control_id"].apply(lambda s: "+".join(sorted(s)))
    aff["control_ids"] = aff["loan_id"].map(ctrls)
    labels["impacted"] = labels["loan_id"].isin(aff["loan_id"].unique())
    labels.to_csv(GROUND_TRUTH / "injected_faults.csv", index=False)
    aff.to_parquet(GROUND_TRUTH / "affected_loan_periods.parquet", index=False)
    to_long(book, correct).to_parquet(GROUND_TRUTH / "correct_ledger.parquet", index=False)
    checkpoint(labels, aff, ledger, book.n)
    print(f"[client_system] done in {time.time() - t0:.1f}s")
    return {"ledger_rows": len(ledger)}


def checkpoint(labels, aff, ledger, n):
    print("\n=== CHECKPOINT - Stage 3: injected faults by control ===")
    s = labels.groupby("control_id").agg(loans=("loan_id", "nunique"), impacted=("impacted", "sum"),
                                         in_double_fault=("n_faults_on_loan", lambda x: int((x > 1).sum())))
    print(s.to_string())
    nl = labels.loan_id.nunique()
    print(f"Faulty loans: {nl} ({nl / n:.2%} of {n}); double-fault loans: {labels[labels.n_faults_on_loan > 1].loan_id.nunique()}")
    print(f"Affected loan-periods (any change > 0.005): {len(aff)}; ledger rows: {len(ledger)}")


if __name__ == "__main__":
    main()
