"""Money rounding: half-up (away from zero), not banker's rounding."""
import numpy as np


def round_half_up(x, decimals: int = 2):
    x = np.asarray(x, dtype=float)
    f = 10.0 ** np.asarray(decimals, dtype=float)
    return np.sign(x) * np.floor(np.abs(x) * f + 0.5 + 1e-7) / f
