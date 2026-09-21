"""Tolerance rule and the implied-offset estimator."""
import numpy as np
from src.audit_engine.compare import tolerance
from src.audit_engine.attribution import implied_offset


def test_tolerance_is_max_of_absolute_and_relative():
    t = tolerance(np.array([100.0, 50_000.0, 5_000_000.0]), 1.0, 0.0001)
    assert list(t) == [1.0, 5.0, 500.0]


def test_implied_offset_uses_first_differing_period():
    # interest per 1% of rate = 100 in each period; first diff 25 -> 0.25%; later periods contaminated
    ref = {"interest": np.array([[1000.0, 1000.0, 1000.0]]), "rate_base": np.array([[100.0, 100.0, 100.0]])}
    sys_ = {"interest": np.array([[1025.0, 1031.0, 1040.0]])}
    assert implied_offset(sys_, ref, 1.0, 0.05)[0] == 0.25
