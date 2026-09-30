"""Smoke test of the Streamlit data layer against the published outputs."""
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import data as D  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def published():
    if not (D.SLIM.exists() and (D.OUT / "audit" / "run_log.json").exists()):
        pytest.skip("outputs missing - run `python run_all.py`")


def test_tables_load_and_join():
    exc, att = D.exceptions(), D.attribution()
    assert D.run_log()["exception_loans"] == exc["loan_id"].nunique() == len(att)
    assert exc["root_cause"].notna().all()
    assert set(D.control_summary()["control_id"]) == {f"C-0{i}" for i in range(1, 10)}


def test_drilldown_of_exception_loan_from_slim_file():
    att = D.attribution()
    loan = att.loc[att["interest_misstatement_inr"].abs().idxmax(), "loan_id"]
    d = D.loan_drilldown(loan)
    assert len(d) and (d["interest_diff"].abs() > 0).any()
    assert D.loan_contract(loan)["loan_id"] == loan
