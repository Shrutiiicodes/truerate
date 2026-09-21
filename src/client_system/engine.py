"""Simulated core banking interest engine (the CLIENT system).

Computes, per loan per billing month: interest, penal charges, and balances.
Correct by default; `Faults` switches reproduce configuration errors.
With resolve=True it also computes customer payment amounts (EMIs, payoff
quotes, prepayment amounts) - used once by the generator to create the
transaction facts, always with faults switched off.

Balance model (both sides use the same business rules):
  principal P  - interest bearing
  arrears   A  - interest booked but unpaid (NOT interest bearing: no compounding)
  penal due D  - penal charges receivable (NOT interest bearing, never capitalised)
Payments are applied D -> A -> P. Part-prepayments reduce P on their value date.
"""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from src.common.calendar import month_start, add_months
from src.common.daycount import day_count, year_basis
from src.common.rounding import round_half_up
from src.common.emi import emi as emi_formula
from src.common.rates import lookup_by_group
from .book import LoanBook

N_MONTHS = 54            # Jan-2021 .. Jun-2025


@dataclass
class Faults:
    rate_offset: np.ndarray
    reset_lag: np.ndarray
    dc30360: np.ndarray
    mor_compound: np.ndarray
    penal_mode: np.ndarray          # 0 none, 1 capitalise, 2 add_to_rate
    daily_round: np.ndarray
    stale_spread: np.ndarray
    accrual_after_close: np.ndarray
    leap365: np.ndarray
    penal_rate_pct: float = 2.0
    daily_decimals: int = 0
    stale_cutoff: int = 0           # int days: product master change date

    @classmethod
    def none(cls, n):
        z = lambda: np.zeros(n, dtype=bool)
        return cls(np.zeros(n), z(), z(), z(), np.zeros(n, dtype=int), z(), z(), z(), z())

    def subset(self, idx):
        kw = {k: (v[idx] if isinstance(v, np.ndarray) else v) for k, v in self.__dict__.items()}
        return Faults(**kw)


@dataclass
class Events:
    pay: np.ndarray          # (n, M) month-end payment amount (EMI / catch-up / final settlement)
    missed: np.ndarray       # (n, M) bool - instalment bounced
    catchup: np.ndarray      # (n, M) bool - generator flag: pay two instalments
    pp_date: np.ndarray      # (n, M) int days, -1 if none
    pp_amt: np.ndarray       # (n, M)
    pp_frac: np.ndarray      # (n, M) generator: fraction of principal prepaid
    fp_date: np.ndarray      # (n,) full prepayment date, -1 if none
    fp_amt: np.ndarray       # (n,)
    emi_amt: np.ndarray = field(default=None)   # (n, M) scheduled EMI in force (resolve output)


def _rate(book: LoanBook, idx, bench_day, spread_day, offset):
    """Contract rate = benchmark(bench_day) + spread(spread_day) + premium (+ fault offset)."""
    fl = book.floating[idx]
    b = lookup_by_group(np.where(fl, book.bench[idx], 0), bench_day, book.bench_curves)
    s = lookup_by_group(np.where(fl, book.prod_idx[idx], -1), spread_day, book.spread_curves)
    return np.where(fl, b + s, book.fixed_base[idx]) + book.premium[idx] + offset


def run(book: LoanBook, ev: Events, faults: Faults | None = None, resolve: bool = False, n_months: int = N_MONTHS):
    n = book.n
    f = faults or Faults.none(n)
    M = n_months
    nan = lambda: np.full((n, M), np.nan)
    out = {k: nan() for k in ["opening_principal", "interest", "penal_charge", "payments",
                              "closing_principal", "interest_arrears", "penal_due", "closing_balance", "rate_end"]}
    P = np.zeros(n); A = np.zeros(n); D = np.zeros(n); R = np.zeros(n); EMI = np.zeros(n)
    closed = np.zeros(n, dtype=bool)
    penal_add_next = np.zeros(n, dtype=bool)
    if resolve:
        ev.emi_amt = np.zeros((n, M))

    for m in range(M):
        ms, me = month_start(m), month_start(m + 1)
        new = np.nonzero(book.disb_m == m)[0]
        if len(new):                                   # disbursal: set up the account
            P[new] = book.principal[new]
            sd = np.where(f.stale_spread[new], np.minimum(book.disb[new], f.stale_cutoff - 1), book.disb[new])
            R[new] = _rate(book, new, book.disb[new], sd, f.rate_offset[new])
        i = np.nonzero((book.disb_m <= m) & ~closed)[0]
        if not len(i):
            continue
        s = np.maximum(ms, book.disb[i])
        fp = ev.fp_date[i]
        fp_in = (fp >= ms) & (fp < me)
        e = np.where(fp_in, fp, me)

        # --- rate reset on the loan's anniversary cycle
        k = m - book.disb_m[i]
        fr = np.maximum(book.freq[i], 1)
        reset_in = book.floating[i] & (book.freq[i] > 0) & (k > 0) & (k % fr == 0)
        rd = add_months(book.disb[i], k)
        reset_in &= rd < e
        bench_day = np.where(f.reset_lag[i], add_months(book.disb[i], np.maximum(k - fr, 0)), rd)
        spread_day = np.where(f.reset_lag[i], bench_day, rd)
        spread_day = np.where(f.stale_spread[i], np.minimum(spread_day, f.stale_cutoff - 1), spread_day)
        R_old = R[i]
        R_new = np.where(reset_in, _rate(book, i, bench_day, spread_day, f.rate_offset[i]), R_old)
        penal_add = np.where(penal_add_next[i], f.penal_rate_pct, 0.0)
        penal_add_next[i] = False

        # --- part prepayment inside the period
        ppd = ev.pp_date[i, m]
        pp_in = (ppd >= s) & (ppd < e)
        P_open = P[i].copy()
        if resolve:
            ev.pp_amt[i, m] = np.where(pp_in, round_half_up(ev.pp_frac[i, m] * P_open, -2), 0.0)
        pp_amt = np.where(pp_in, np.nan_to_num(ev.pp_amt[i, m]), 0.0)

        # --- constant-balance/constant-rate segments
        conv = np.where(f.dc30360[i], 2, book.conv[i])
        b1 = np.where(reset_in, rd, e)
        b2 = np.where(pp_in, ppd, e)
        x1, x2 = np.minimum(b1, b2), np.maximum(b1, b2)
        raw = np.zeros(len(i))
        for a, b in ((s, x1), (x1, x2), (x2, e)):
            bal = P_open - np.where(pp_in & (a >= ppd), pp_amt, 0.0)
            rate = np.where(reset_in & (a >= rd), R_new, R_old) + penal_add
            raw += _segment_interest(bal, rate, a, b, conv, f, i)
        P_end = P_open - pp_amt
        extra = f.accrual_after_close[i] & fp_in                # C-08
        if extra.any():
            raw += np.where(extra, _segment_interest(P_end, R_new, e, np.full(len(i), me), conv, f, i), 0.0)
        interest = round_half_up(raw, 2)

        # --- penal charges (fixed amount per bounced instalment)
        missed = ev.missed[i, m]
        charge = np.where(missed, book.penal_amt[i], 0.0)
        pm = np.where(m >= book.switch_m[i], f.penal_mode[i], 0)
        cap = (pm == 1) & missed
        penal_add_next[i[(pm == 2) & missed]] = True
        charge = np.where((pm == 2) & missed, 0.0, charge)

        # --- book interest and charges
        mor_month = (m > book.disb_m[i]) & (m <= book.disb_m[i] + book.mor[i])
        compound = f.mor_compound[i] & mor_month               # C-04
        A_i = A[i] + np.where(compound, 0.0, interest)
        P_end = P_end + np.where(compound, interest, 0.0) + np.where(cap, charge, 0.0)
        D_i = D[i] + np.where(cap, 0.0, charge)

        # --- payments
        last = m == book.last_m[i]
        if resolve:
            payoff = np.maximum(P_end + A_i + D_i, 0.0)
            ev.fp_amt[i] = np.where(fp_in, round_half_up(payoff, 2), ev.fp_amt[i])
            emi_mo = book.is_emi[i] & (m >= book.first_emi_m[i]) & ~last & ~fp_in
            pay_me = np.where(last & ~fp_in, round_half_up(payoff, 2),
                              np.where(emi_mo & ~ev.missed[i, m], EMI[i] * np.where(ev.catchup[i, m], 2, 1), 0.0))
            ev.pay[i, m] = pay_me
        pay_me = np.nan_to_num(ev.pay[i, m])
        pay = pay_me + np.where(fp_in, ev.fp_amt[i], 0.0)
        x = np.minimum(np.maximum(pay, 0), np.maximum(D_i, 0)); D_i -= x; rem = pay - x
        y = np.minimum(rem, np.maximum(A_i, 0)); A_i -= y; rem -= y
        P_end = P_end - rem

        if resolve:                                             # EMI (re)calculation, tenure unchanged
            init = book.is_emi[i] & (m == book.first_emi_m[i] - 1)
            rec = book.is_emi[i] & ((reset_in & (R_new != R_old)) | pp_in) & (m >= book.first_emi_m[i]) & (m < book.last_m[i])
            remaining = np.where(init, book.tenure[i], book.last_m[i] - m)
            EMI[i] = np.where(init | rec, emi_formula(np.maximum(P_end, 0), R_new, remaining), EMI[i])
            ev.emi_amt[i, m] = EMI[i]

        # --- write ledger row
        out["opening_principal"][i, m] = P_open
        out["interest"][i, m] = interest
        out["penal_charge"][i, m] = np.where(missed, np.where((pm == 2), 0.0, book.penal_amt[i]), 0.0)
        out["payments"][i, m] = pay + pp_amt
        out["closing_principal"][i, m] = P_end
        out["interest_arrears"][i, m] = A_i
        out["penal_due"][i, m] = D_i
        out["closing_balance"][i, m] = P_end + A_i + D_i
        out["rate_end"][i, m] = R_new
        P[i], A[i], D[i], R[i] = P_end, A_i, D_i, R_new
        closed[i] = fp_in | last
    return out


def _segment_interest(bal, rate_pct, a, b, conv, f: Faults, i):
    nd = day_count(a, b, conv)
    basis = year_basis(a, conv, force_365=f.leap365[i])
    daily = bal * rate_pct / 100.0 / basis
    rounded = round_half_up(daily, f.daily_decimals) * nd                 # C-06
    return np.where(b > a, np.where(f.daily_round[i], rounded, daily * nd), 0.0)
