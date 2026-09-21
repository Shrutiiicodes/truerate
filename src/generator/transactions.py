"""Stage 2b: transaction facts. A behavioural skeleton (which months bounce,
when customers prepay) is drawn first; amounts (EMIs, prepayment and payoff
quotes) are then resolved by running the core banking engine in CORRECT mode.
Those amounts become fixed facts shared by the client system and the auditor."""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.common.calendar import month_start, from_days
from src.client_system.book import LoanBook
from src.client_system.engine import Events, run, N_MONTHS


def _uniform_month(rng, lo, hi):
    """Random integer in [lo, hi] per row (hi >= lo assumed where used)."""
    return lo + np.floor(rng.random(len(lo)) * (hi - lo + 1)).astype(int)


def build_skeleton(book: LoanBook, cfg: dict, rng: np.random.Generator) -> Events:
    n, M = book.n, N_MONTHS
    beh = cfg["behaviour"]
    months = np.arange(M)[None, :]
    last_obs = np.minimum(book.last_m, M - 1)

    # Full prepayment (closure) month and date
    fp_share = np.array([beh["full_prepay_share"][p] for p in book.product])
    fp_lo = np.where(book.is_emi, book.first_emi_m + 3, book.disb_m + 1)
    fp_hi = np.minimum(book.last_m - 1, M - 1)
    has_fp = (rng.random(n) < fp_share) & (fp_hi >= fp_lo)
    fp_m = np.where(has_fp, _uniform_month(rng, fp_lo, np.maximum(fp_hi, fp_lo)), 10_000)
    fp_date = np.where(has_fp, month_start(np.minimum(fp_m, M - 1)) + rng.integers(2, 27, n), -1)
    alive_before_fp = months < fp_m[:, None]

    # Missed instalments (no two in a row), with catch-up next month
    p_miss = np.array([beh["missed_emi_prob"][p] for p in book.product])
    emi_window = book.is_emi[:, None] & (months >= book.first_emi_m[:, None]) & (months < book.last_m[:, None])
    emi_window &= months <= last_obs[:, None]
    missed = (rng.random((n, M)) < p_miss[:, None]) & emi_window & alive_before_fp
    missed[:, 1:] &= ~missed[:, :-1]
    catch = np.zeros_like(missed)
    catch[:, 1:] = missed[:, :-1] & (rng.random((n, M - 1)) < beh["catch_up_prob"])
    catch &= emi_window & alive_before_fp & ~missed

    # Part prepayment (one per selected loan)
    pp_share = np.array([beh["partial_prepay_share"][p] for p in book.product])
    pp_lo = book.first_emi_m + 1
    pp_hi = np.minimum(np.minimum(book.last_m - 3, M - 1), fp_m - 1)
    has_pp = book.is_emi & (rng.random(n) < pp_share) & (pp_hi >= pp_lo)
    pp_m = _uniform_month(rng, pp_lo, np.maximum(pp_hi, pp_lo))
    pp_date = np.full((n, M), -1, dtype=np.int64)
    pp_frac = np.zeros((n, M))
    r = np.nonzero(has_pp)[0]
    pp_date[r, pp_m[r]] = month_start(pp_m[r]) + rng.integers(3, 26, len(r))
    lo, hi = beh["partial_prepay_fraction"]
    pp_frac[r, pp_m[r]] = np.round(rng.uniform(lo, hi, len(r)), 3)

    return Events(pay=np.full((n, M), np.nan), missed=missed, catchup=catch, pp_date=pp_date,
                  pp_amt=np.zeros((n, M)), pp_frac=pp_frac, fp_date=fp_date.astype(np.int64), fp_amt=np.zeros(n))


def resolve_and_tabulate(book: LoanBook, ev: Events) -> pd.DataFrame:
    run(book, ev, faults=None, resolve=True)
    M = ev.pay.shape[1]
    month_end = month_start(np.arange(M) + 1) - 1
    rows = []
    rows.append(pd.DataFrame({"loan_id": book.loan_id, "txn_date": book.disb, "txn_type": "DISBURSAL",
                              "amount_inr": book.principal, "instalment_due_inr": 0.0}))
    li, mi = np.nonzero(np.nan_to_num(ev.pay) > 0)
    final = mi == book.last_m[li]
    typ = np.where(final, "FINAL_SETTLEMENT", np.where(ev.catchup[li, mi], "EMI_CATCH_UP", "EMI"))
    due = ev.emi_amt[li, np.maximum(mi - 1, 0)]
    rows.append(pd.DataFrame({"loan_id": book.loan_id[li], "txn_date": month_end[mi], "txn_type": typ,
                              "amount_inr": ev.pay[li, mi], "instalment_due_inr": np.where(final, ev.pay[li, mi], due)}))
    li, mi = np.nonzero(ev.missed)
    rows.append(pd.DataFrame({"loan_id": book.loan_id[li], "txn_date": month_end[mi], "txn_type": "EMI_BOUNCED",
                              "amount_inr": 0.0, "instalment_due_inr": ev.emi_amt[li, np.maximum(mi - 1, 0)]}))
    li, mi = np.nonzero(ev.pp_date >= 0)
    rows.append(pd.DataFrame({"loan_id": book.loan_id[li], "txn_date": ev.pp_date[li, mi], "txn_type": "PART_PREPAYMENT",
                              "amount_inr": ev.pp_amt[li, mi], "instalment_due_inr": 0.0}))
    li = np.nonzero(ev.fp_date >= 0)[0]
    rows.append(pd.DataFrame({"loan_id": book.loan_id[li], "txn_date": ev.fp_date[li], "txn_type": "FULL_PREPAYMENT",
                              "amount_inr": ev.fp_amt[li], "instalment_due_inr": 0.0}))
    tx = pd.concat(rows, ignore_index=True)
    tx = tx.sort_values(["loan_id", "txn_date", "txn_type"], kind="stable").reset_index(drop=True)
    tx["txn_date"] = from_days(tx["txn_date"].to_numpy()).astype(str)
    tx["amount_inr"] = tx["amount_inr"].round(2)
    tx["instalment_due_inr"] = tx["instalment_due_inr"].round(2)
    tx.insert(0, "txn_id", [f"TX{k:08d}" for k in range(1, len(tx) + 1)])
    return tx
