"""Regression guard on the README's headline numbers. Fixed seeds make every figure
reproducible, so any code change that moves them must be deliberate (update README
and these values together). Reads the outputs of `python run_all.py`."""
import json
from pathlib import Path
import pytest

OUT = Path(__file__).resolve().parents[1] / "outputs"


@pytest.fixture(scope="module")
def results():
    log, ev = OUT / "audit" / "run_log.json", OUT / "evaluation_report.json"
    if not (log.exists() and ev.exists()):
        pytest.skip("outputs missing - run `python run_all.py`")
    return json.loads(log.read_text(encoding="utf-8")), json.loads(ev.read_text(encoding="utf-8"))


def test_population_and_exceptions(results):
    log, _ = results
    assert log["completeness"]["loans_in_master_file"] == 50_000
    assert log["completeness"]["expected_loan_periods"] == 1_296_378
    assert log["completeness"]["rows_missing_in_system"] == log["completeness"]["rows_extra_in_system"] == 0
    assert log["exception_loan_periods"] == 27_458
    assert log["exception_loans"] == 1_416
    assert log["attribution_status"] == {"Attributed": 1_415, "Unexplained": 1}


def test_detection_and_attribution_quality(results):
    _, ev = results
    loan = ev["detection_vs_any_change"]["loan_level"]
    assert (loan["tp"], loan["fp"], loan["fn"]) == (1_416, 0, 2)
    assert ev["detection_vs_above_tolerance_changes"]["loan_period_level"]["recall"] == 1.0
    assert ev["attribution"]["exact_match_accuracy"] >= 0.997
    assert ev["misstatement"]["detected_share_of_injected_net"] == pytest.approx(1.0, abs=0.001)
