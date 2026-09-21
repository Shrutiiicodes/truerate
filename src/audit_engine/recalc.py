"""Independent recalculation from first principles.

For each billing month, the period [start, end) is split at the (at most two)
dates where the balance or the rate changes - a rate reset and a part
prepayment. Interest = sum over segments of balance x rate x day fraction,
rounded half-up to 2 dp once per period. No per-day rows are ever built.

A `Hypothesis` switches on one or more candidate configuration errors; the
baseline hypothesis is the documented business rule set.
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
import numpy as np
from src.common.calendar import month_start, add_months
from src.common.daycount import day_count, year_basis
from src.common.rounding import round_half_up
from .population import Population, N_MONTHS


@dataclass(frozen=True)
class Hypothesis:
    name: str = "baseline"
    controls: tuple = ()
    rate_offset: object = 0.0          # scalar or per-loan array (% p.a.)
    reset_lag: bool = False
    thirty_360: bool = False
    compound_moratorium: bool = False
    penal_mode: str = "fee"            # fee | capitalise | add_to_rate
    penal_rate: float = 0.0
    daily_decimals: int | None = None
    stale_spread: bool = False
    accrue_after_close: bool = False
    leap_365: bool = False

    def __add__(self, other: "Hypothesis") -> "Hypothesis":
        """Combine two single-fault hypotheses into a pair hypothesis."""
        pick = lambda a, b, default: b if b != default else a
        return Hypothesis(
            name=f"{self.name} + {other.name}", controls=self.controls + other.controls,
            rate_offset=other.rate_offset if np.any(np.asarray(other.rate_offset) != 0) else self.rate_offset,
            reset_lag=self.reset_lag or other.reset_lag, thirty_360=self.thirty_360 or other.thirty_360,
            compound_moratorium=self.compound_moratorium or other.compound_moratorium,
            penal_mode=pick(self.penal_mode, other.penal_mode, "fee"), penal_rate=max(self.penal_rate, other.penal_rate),
            daily_decimals=other.daily_decimals if other.daily_decimals is not None else self.daily_decimals,
            stale_spread=self.stale_spread or other.stale_spread,
            accrue_after_close=self.accrue_after_close or other.accrue_after_close,
            leap_365=self.leap_365 or other.leap_365)


BASELINE = Hypothesis()


def contract_rate(pop: Population, rows, bench_day, spread_day, offset) -> np.ndarray:
    """benchmark + product spread + loan premium for floating loans; card rate + premium for fixed."""
    out = pop.card_rate[rows] + pop.premium[rows]
    fl = np.nonzero(pop.floating[rows])[0]
    if len(fl):
        r = rows[fl]
        b = np.zeros(len(fl)); s = np.zeros(len(fl))
        for name, curve in pop.benchmarks.items():
            k = pop.bm[r] == name
            if k.any(): b[k] = curve.at(bench_day[fl][k])
        for pi, curve in pop.spreads.items():
            k = pop.p_idx[r] == pi
            if curve is not None and k.any(): s[k] = curve.at(spread_day[fl][k])
        out[fl] = b + s + pop.premium[r]
    return out + offset


def recalculate(pop: Population, h: Hypothesis = BASELINE) -> dict:
    n = pop.size
    off = np.broadcast_to(np.asarray(h.rate_offset, float), (n,))
    res = {k: np.full((n, N_MONTHS), np.nan) for k in
           ["interest", "penal_charge", "closing_principal", "closing_balance", "rate_base", "opening_principal"]}
    princ = np.zeros(n); arrears = np.zeros(n); fees = np.zeros(n); rate = np.zeros(n)
    done = np.zeros(n, bool); surcharge = np.zeros(n)
    stale = h.stale_spread & (pop.stale_cutoff > 0) & (pop.disb < pop.stale_cutoff)

    for m in range(N_MONTHS):
        p_start, p_end = month_start(m), month_start(m + 1)
        opened = np.nonzero(pop.disb_m == m)[0]
        if len(opened):
            princ[opened] = pop.principal[opened]
            sday = np.where(stale[opened], np.minimum(pop.disb[opened], pop.stale_cutoff[opened] - 1), pop.disb[opened])
            rate[opened] = contract_rate(pop, opened, pop.disb[opened], sday, off[opened])
        r = np.nonzero((pop.disb_m <= m) & ~done)[0]
        if len(r) == 0:
            continue
        start = np.maximum(p_start, pop.disb[r])
        closes = (pop.close_day[r] >= p_start) & (pop.close_day[r] < p_end)
        end = np.where(closes, pop.close_day[r], p_end)

        # reset dates fall on disbursal anniversaries every `reset_months`
        age = m - pop.disb_m[r]
        cyc = np.where(pop.reset_months[r] > 0, pop.reset_months[r], 1)
        is_reset = pop.floating[r] & (pop.reset_months[r] > 0) & (age > 0) & (age % cyc == 0)
        reset_day = add_months(pop.disb[r], age)
        is_reset &= reset_day < end
        ref_day = add_months(pop.disb[r], np.maximum(age - cyc, 0)) if h.reset_lag else reset_day
        spr_day = np.where(stale[r], np.minimum(ref_day, pop.stale_cutoff[r] - 1), ref_day)
        before = rate[r]
        after = np.where(is_reset, contract_rate(pop, r, ref_day, spr_day, off[r]), before)

        ppd = pop.pp_day[r, m]
        has_pp = (ppd >= start) & (ppd < end)
        ppa = np.where(has_pp, pop.pp_amt[r, m], 0.0)
        opening = princ[r].copy()

        # segment the period at the reset date and the prepayment date
        conv = np.full(len(r), 2) if h.thirty_360 else pop.dc[r]
        cuts = np.sort(np.stack([np.where(is_reset, reset_day, end), np.where(has_pp, ppd, end)]), axis=0)
        bounds = [start, cuts[0], cuts[1], end]
        acc = np.zeros(len(r)); base = np.zeros(len(r))
        for a, b in zip(bounds[:-1], bounds[1:]):
            bal = opening - np.where(has_pp & (a >= ppd), ppa, 0.0)
            roi = np.where(is_reset & (a >= reset_day), after, before) + surcharge[r]
            i_seg, frac = _accrue(bal, roi, a, b, conv, h, pop.dc[r])
            acc += i_seg; base += bal * frac / 100.0
        closing_p = opening - ppa
        if h.accrue_after_close and closes.any():
            tail, _ = _accrue(closing_p, after, end, np.full(len(r), p_end), conv, h, pop.dc[r])
            acc += np.where(closes, tail, 0.0)
        interest = round_half_up(acc, 2)
        surcharge[r] = 0.0

        # penal charge: fixed fee per bounced instalment (baseline rule)
        bounce = pop.bounced[r, m]
        legacy = (m >= pop.regime_m[r]) & bounce
        fee = np.where(bounce, pop.penal_fee[r], 0.0)
        cap_fee = np.zeros(len(r))
        if h.penal_mode == "capitalise":
            cap_fee = np.where(legacy, fee, 0.0)
        elif h.penal_mode == "add_to_rate":
            fee = np.where(legacy, 0.0, fee)
            surcharge[r[legacy]] = h.penal_rate

        in_mor = (m > pop.disb_m[r]) & (m <= pop.disb_m[r] + pop.mor[r])
        cap_int = np.where(in_mor, interest, 0.0) if h.compound_moratorium else np.zeros(len(r))
        arr = arrears[r] + interest - cap_int
        pen = fees[r] + fee - cap_fee
        closing_p = closing_p + cap_int + cap_fee

        # payments: penal dues first, then interest, then principal
        cash = pop.pay[r, m] + np.where(closes, pop.close_amt[r], 0.0)
        to_pen = np.minimum(cash, np.maximum(pen, 0)); pen = pen - to_pen; cash = cash - to_pen
        to_int = np.minimum(cash, np.maximum(arr, 0)); arr = arr - to_int; cash = cash - to_int
        closing_p = closing_p - cash

        res["opening_principal"][r, m] = opening
        res["interest"][r, m] = interest
        res["penal_charge"][r, m] = fee          # booked charge (capitalised or not)
        res["closing_principal"][r, m] = closing_p
        res["closing_balance"][r, m] = closing_p + arr + pen
        res["rate_base"][r, m] = base
        princ[r], arrears[r], fees[r], rate[r] = closing_p, arr, pen, after
        done[r] = closes | (m == pop.maturity_m[r])
    return res


def _accrue(bal, roi, a, b, conv, h: Hypothesis, product_dc):
    """Interest for [a, b) at constant balance and rate; returns (interest, year fraction)."""
    days = day_count(a, b, conv)
    basis = year_basis(a, conv, force_365=np.full(len(a), h.leap_365) & (product_dc == 1))
    per_day = bal * roi / 100.0 / basis
    live = b > a
    if h.daily_decimals is not None:
        return np.where(live, round_half_up(per_day, h.daily_decimals) * days, 0.0), np.where(live, days / basis, 0.0)
    return np.where(live, per_day * days, 0.0), np.where(live, days / basis, 0.0)
