"""Data access for the Streamlit viewer (kept separate so it can be unit-tested
without Streamlit). Reads published outputs only."""
from __future__ import annotations
import json
import sys
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "outputs"
GEN = ROOT / "data" / "generated"


def ensure_data():
    required_files = [
        OUT / "audit" / "run_log.json",
        OUT / "audit" / "control_summary.csv",
        OUT / "audit" / "exception_loans_attribution.csv",
        OUT / "audit" / "exceptions.parquet",
        OUT / "audit" / "expected_ledger.parquet",
        GEN / "loans.parquet",
        GEN / "system_interest_ledger.parquet",
    ]
    if any(not p.exists() for p in required_files):
        from src.generator.run import main as generate
        from src.client_system.run import main as client
        from src.audit_engine.run import main as audit
        from src.reporting.run import main as report
        from src.evaluation.evaluate import main as evaluate
        generate()
        client()
        audit()
        report()
        evaluate()


def run_log() -> dict:
    ensure_data()
    return json.loads((OUT / "audit" / "run_log.json").read_text(encoding="utf-8"))


def control_summary() -> pd.DataFrame:
    return pd.read_csv(OUT / "audit" / "control_summary.csv")


def attribution() -> pd.DataFrame:
    return pd.read_csv(OUT / "audit" / "exception_loans_attribution.csv")


def exceptions() -> pd.DataFrame:
    e = pd.read_parquet(OUT / "audit" / "exceptions.parquet")
    a = attribution().set_index("loan_id")
    e["root_cause"] = e["loan_id"].map(a["control_ids"]).fillna("UNEXPLAINED")
    e["status"] = e["loan_id"].map(a["status"])
    return e


def loan_drilldown(loan_id: str) -> pd.DataFrame:
    """Expected vs system per period for one loan."""
    exp = pd.read_parquet(OUT / "audit" / "expected_ledger.parquet", filters=[("loan_id", "==", loan_id)])
    sys_ = pd.read_parquet(GEN / "system_interest_ledger.parquet", filters=[("loan_id", "==", loan_id)])
    cols = ["interest", "penal_charge", "closing_principal", "closing_balance"]
    d = exp[["period"] + cols].merge(sys_[["period"] + cols], on="period", how="outer", suffixes=("_expected", "_system"))
    for c in cols:
        d[f"{c}_diff"] = (d[f"{c}_system"] - d[f"{c}_expected"]).round(2)
    return d.sort_values("period").reset_index(drop=True)


def loan_contract(loan_id: str) -> dict:
    loans = pd.read_parquet(GEN / "loans.parquet", filters=[("loan_id", "==", loan_id)])
    return loans.iloc[0].to_dict() if len(loans) else {}


def evaluation_markdown() -> str:
    p = OUT / "evaluation_report.md"
    return p.read_text(encoding="utf-8") if p.exists() else "_Run `python run_all.py` to produce the evaluation report._"


def evaluation_json() -> dict:
    p = OUT / "evaluation_report.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
