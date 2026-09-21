"""Audit-side summaries for the deliverables. Reads audit outputs and
auditor-visible data only (no ground truth)."""
from __future__ import annotations
import json
from dataclasses import dataclass
import numpy as np
import pandas as pd
from src.common.config import load_yaml
from src.common.io import load_table
from src.common.paths import OUTPUTS
from src.common.calendar import month_index
from src.audit_engine.population import load_population

AUD = OUTPUTS / "audit"
CONTROLS = [f"C-0{k}" for k in range(1, 10)]


@dataclass
class AuditResults:
    cfg: dict
    rcm_cfg: dict
    log: dict
    exc: pd.DataFrame
    att: pd.DataFrame
    alloc: pd.DataFrame
    expected: pd.DataFrame
    system: pd.DataFrame
    pop: object
    raw: dict


def load_results() -> AuditResults:
    pop, ledger, raw = load_population()
    return AuditResults(
        cfg=load_yaml("audit.yaml"), rcm_cfg=load_yaml("rcm.yaml"),
        log=json.loads((AUD / "run_log.json").read_text()),
        exc=pd.read_parquet(AUD / "exceptions.parquet"),
        att=pd.read_csv(AUD / "exception_loans_attribution.csv"),
        alloc=pd.read_csv(AUD / "impact_by_control.csv"),
        expected=pd.read_parquet(AUD / "expected_ledger.parquet"),
        system=ledger, pop=pop, raw=raw)


def control_populations(r: AuditResults) -> dict:
    pop, exp = r.pop, r.expected
    m = (exp["period"].str[:4].astype(int) - 2021) * 12 + exp["period"].str[5:7].astype(int) - 1
    close_m = np.where(pop.close_day >= 0, month_index(np.maximum(pop.close_day, 0)), pop.maturity_m)
    last = np.minimum(close_m, 53)
    fl = pop.floating & (pop.reset_months > 0)
    freq = np.where(fl, pop.reset_months, 1)
    resets = np.where(fl, np.maximum((last - pop.disb_m) // freq, 0), 0)
    cutoff = pop.stale_cutoff
    cm = np.where(cutoff > 0, month_index(np.maximum(cutoff, 1)), 999)
    k_first = np.ceil(np.maximum(cm - pop.disb_m, 1) / freq).astype(int)
    post_change = np.where(fl & (cutoff > 0) & (pop.disb < cutoff),
                           np.maximum((last - pop.disb_m) // freq - k_first + 1, 0), 0)
    pos = pd.Index(pop.loan_id).get_indexer(exp["loan_id"])
    in_mor = (m.to_numpy() > pop.disb_m[pos]) & (m.to_numpy() <= pop.disb_m[pos] + pop.mor[pos])
    bounced = int(pop.bounced.sum())
    bi, bm = np.nonzero(pop.bounced)
    in_regime = int((bm >= pop.regime_m[bi]).sum())
    closures = int(((pop.close_day >= 0) | (pop.maturity_m <= 53)).sum())
    actact_2024 = int(((pop.dc[pos] == 1) & exp["period"].str.startswith("2024").to_numpy()).sum())
    lp = len(exp)
    return {
        "C-01": ("All loan-periods (rate applied every period)", lp),
        "C-02": ("Rate reset events on floating loans", int(resets.sum())),
        "C-03": ("All loan-periods", lp),
        "C-04": ("Loan-periods inside a moratorium", int(in_mor.sum())),
        "C-05": (f"Bounced instalments ({in_regime:,} under the 2024 penal-charge regime)", bounced),
        "C-06": ("All loan-periods", lp),
        "C-07": ("HL-FLT resets on/after the 01-Oct-2023 spread change (pre-change loans)", int(post_change.sum())),
        "C-08": ("Loan closures in window (prepayment or maturity)", closures),
        "C-09": ("ACT/ACT loan-periods in leap year 2024", actact_2024),
    }


def loan_period_detail(r: AuditResults) -> pd.DataFrame:
    keys = r.exc[["loan_id", "period"]].drop_duplicates()
    breached = r.exc.groupby(["loan_id", "period"])["metric"].apply(lambda s: ", ".join(sorted(s))).rename("metrics_breached")
    e = r.expected.merge(keys, on=["loan_id", "period"])
    s = r.system[["loan_id", "period", "interest", "penal_charge", "closing_balance"]]
    d = e.merge(s, on=["loan_id", "period"], suffixes=("_expected", "_system"))
    d = d.join(breached, on=["loan_id", "period"])
    a = r.att.set_index("loan_id")
    d["attribution_status"] = d["loan_id"].map(a["status"])
    d["root_cause_controls"] = d["loan_id"].map(a["control_ids"]).fillna("")
    d["interest_diff"] = (d["interest_system"] - d["interest_expected"]).round(2)
    d["penal_diff"] = (d["penal_charge_system"] - d["penal_charge_expected"]).round(2)
    d["balance_diff"] = (d["closing_balance_system"] - d["closing_balance_expected"]).round(2)
    cols = ["loan_id", "product_code", "period", "root_cause_controls", "attribution_status", "metrics_breached",
            "interest_expected", "interest_system", "interest_diff", "penal_charge_expected", "penal_charge_system",
            "penal_diff", "closing_balance_expected", "closing_balance_system", "balance_diff"]
    return d[cols].sort_values(["loan_id", "period"]).reset_index(drop=True)


def period_differences(r: AuditResults) -> pd.DataFrame:
    """System - expected per loan-period for all rows (incl. sub-tolerance)."""
    d = r.expected[["loan_id", "period", "interest", "penal_charge"]].merge(
        r.system[["loan_id", "period", "interest", "penal_charge"]], on=["loan_id", "period"], suffixes=("_e", "_s"))
    d["diff"] = (d.interest_s - d.interest_e) + (d.penal_charge_s - d.penal_charge_e)
    d["interest_expected"] = d["interest_e"]
    return d[["loan_id", "period", "diff", "interest_expected"]]


def control_period_impact(r: AuditResults, pdiff: pd.DataFrame) -> pd.DataFrame:
    """Loan-period differences allocated to controls (pairs split by the loan-level allocation shares)."""
    al = r.alloc.copy()
    tot = al.groupby("loan_id")["impact_inr"].transform("sum")
    al["share"] = np.where(tot.abs() > 0, al["impact_inr"] / tot.replace(0, np.nan), 1 / al.groupby("loan_id")["impact_inr"].transform("size"))
    al["share"] = al["share"].fillna(1.0)
    x = pdiff[pdiff.loan_id.isin(al.loan_id)].merge(al[["loan_id", "control_id", "share"]], on="loan_id")
    x["impact"] = x["diff"] * x["share"]
    return x


def materiality(r: AuditResults, pdiff: pd.DataFrame, cpi: pd.DataFrame) -> dict:
    m = r.cfg["materiality"]
    fy = m["financial_year"]
    in_fy = lambda p: (p >= fy["start"]) & (p <= fy["end"])
    basis = float(pdiff.loc[in_fy(pdiff.period), "interest_expected"].sum())
    overall = basis * m["overall_pct_of_basis"]
    pm = overall * m["performance_pct_of_overall"]
    ct = overall * m["clearly_trivial_pct_of_overall"]
    fy_diff = pdiff[in_fy(pdiff.period)]
    net = float(fy_diff["diff"].sum())
    gross = float(fy_diff["diff"].abs().sum())
    per_ctrl = cpi[in_fy(cpi.period)].groupby("control_id")["impact"].agg(net="sum", gross=lambda s: s.abs().sum())
    window = pdiff.groupby(pdiff.period.str[:4])["diff"].sum()
    return {"fy_label": fy["label"], "basis_interest_income": basis, "overall_materiality": overall,
            "performance_materiality": pm, "clearly_trivial": ct, "fy_net_misstatement": net,
            "fy_gross_misstatement": gross, "per_control": per_ctrl, "by_calendar_year_net": window,
            "overall_pct": m["overall_pct_of_basis"], "pm_pct": m["performance_pct_of_overall"],
            "ct_pct": m["clearly_trivial_pct_of_overall"],
            "is_material": abs(net) >= overall, "exceeds_pm": abs(net) >= pm, "above_ct": abs(net) >= ct}


def control_summary(r: AuditResults, mat: dict) -> pd.DataFrame:
    pops = control_populations(r)
    rows = []
    esc = set(r.cfg["deficiency_classification"]["qualitative_escalation"])
    att = r.att
    lp = r.exc[["loan_id", "period"]].drop_duplicates()
    for c in CONTROLS:
        info = r.rcm_cfg["controls"][c]
        hit = att[(att.status == "Attributed") & att.control_ids.fillna("").str.contains(c)]
        n_loans = len(hit)
        n_lp = int(lp.loan_id.isin(hit.loan_id).sum())
        imp = r.alloc[r.alloc.control_id == c]
        net, gross = float(imp.impact_inr.sum()), float(imp.impact_inr.abs().sum())
        pc = mat["per_control"].loc[c] if c in mat["per_control"].index else pd.Series({"net": 0.0, "gross": 0.0})
        if n_loans == 0:
            concl, cls = "Effective", "No deficiency"
        else:
            concl = "Deficient"
            if abs(pc["gross"]) >= mat["performance_materiality"]:
                cls = "Potential material weakness - escalate"
            elif c in esc or abs(pc["gross"]) >= mat["clearly_trivial"]:
                cls = "Significant deficiency" + (" (qualitative: regulatory / ITGC)" if c in esc else "")
            else:
                cls = "Control deficiency (below clearly trivial; systematic)"
        rows.append({"control_id": c, "control_name": info["name"], "process": r.rcm_cfg["process"],
                     "risk": info["risk"], "control_description": info["control"], "control_type": info["type"],
                     "test_procedure": info["procedure"], "population_description": pops[c][0],
                     "population_size": pops[c][1], "loans_with_exceptions": n_loans, "exception_loan_periods": n_lp,
                     "impact_net_window_inr": round(net, 2), "impact_gross_window_inr": round(gross, 2),
                     "impact_net_fy_inr": round(float(pc["net"]), 2), "impact_gross_fy_inr": round(float(pc["gross"]), 2),
                     "conclusion": concl, "deficiency_classification": cls, "recommendation": info["recommendation"]})
    return pd.DataFrame(rows)
