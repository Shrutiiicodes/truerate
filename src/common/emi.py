"""Equated monthly instalment."""
import numpy as np
from .rounding import round_half_up


def emi(principal, annual_rate_pct, n_months, round_to_rupee: bool = True):
    """Reducing-balance EMI: P*r*(1+r)^n / ((1+r)^n - 1), r = annual rate / 12.
    Rounded half-up to the rupee (bank practice)."""
    p = np.asarray(principal, dtype=float)
    r = np.asarray(annual_rate_pct, dtype=float) / 1200.0
    n = np.maximum(np.asarray(n_months, dtype=float), 1.0)
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        g = (1.0 + r) ** n
        val = np.where(r > 0, p * r * g / (g - 1.0), p / n)
    val = np.maximum(np.nan_to_num(val), 0.0)
    return round_half_up(val, 0) if round_to_rupee else val
