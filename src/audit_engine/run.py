"""Stage 4-5 driver: full-population recalculation, exception identification,
root-cause attribution. Reads only auditor-visible data; writes to outputs/audit/."""
from __future__ import annotations
import json
import time
import numpy as np
import pandas as pd
from src.common.config import load_yaml
from src.common.paths import OUTPUTS
from src.common.calendar import period_label
from .population import load_population, system_dense, METRICS
from .recalc import recalculate, BASELINE
from .compare import exceptions_table
from .attribution import attribute, CONTROL_OF

AUDIT_OUT = OUTPUTS / "audit"


def expected_long(pop, exp) -> pd.DataFrame:
    li, mi = np.nonzero(~np.isnan(exp["interest"]))
    df = pd.DataFrame({"loan_id": pop.loan_id[li], "product_code": pop.product[li], "period": period_label(mi)})
    for c in METRICS + ["opening_principal"]:
        df[c] = np.round(exp[c][li, mi], 2)
    return df


def main() -> dict:
    cfg = load_yaml("audit.yaml")
    tol = cfg["tolerance"]
    AUDIT_OUT.mkdir(parents=True, exist_ok=True)
    timings = {}
    t0 = time.time()
    pop, ledger, raw = load_population()
    sys = system_dense(pop, ledger)
    timings["load_seconds"] = round(time.time() - t0, 2)

    t1 = time.time()
    exp = recalculate(pop, BASELINE)
    timings["recalculation_seconds"] = round(time.time() - t1, 2)
    print(f"[audit_engine] full-population recalculation: {pop.size:,} loans, "
          f"{int((~np.isnan(exp['interest'])).sum()):,} loan-periods in {timings['recalculation_seconds']}s")

    t2 = time.time()
    exc = exceptions_table(pop, exp, sys, tol["absolute_inr"], tol["relative"])
    timings["comparison_seconds"] = round(time.time() - t2, 2)

    # completeness / population reconciliation
    exp_rows = int((~np.isnan(exp["interest"])).sum())
    completeness = {
        "loans_in_master_file": int(pop.size),
        "loans_in_system_ledger": int(ledger["loan_id"].nunique()),
        "loans_in_transactions": int(raw["transactions"]["loan_id"].nunique()),
        "system_ledger_rows": int(len(ledger)),
        "expected_loan_periods": exp_rows,
        "ledger_rows_for_unknown_loans": sys["_unknown_loan_rows"],
        "rows_missing_in_system": int((exc["metric"] == "row_missing_in_system").sum()),
        "rows_extra_in_system": int((exc["metric"] == "row_extra_in_system").sum()),
        "disbursed_principal_master_inr": float(pop.principal.sum()),
        "disbursed_principal_transactions_inr": float(raw["transactions"].query("txn_type=='DISBURSAL'")["amount_inr"].sum()),
    }

    # attribution on exception loans
    t3 = time.time()
    exc_loans = exc["loan_id"].unique()
    idx = np.nonzero(np.isin(pop.loan_id, exc_loans))[0]
    sub = pop.take(idx)
    subsys = {k: v[idx] for k, v in sys.items() if isinstance(v, np.ndarray)}
    att, base, single_ledgers = attribute(sub, subsys, tol["absolute_inr"], tol["relative"], cfg["attribution"])
    timings["attribution_seconds"] = round(time.time() - t3, 2)

    # rupee impact per loan (system - expected, all periods of the loan)
    d_int = np.nansum(subsys["interest"] - base["interest"], axis=1)
    d_pen = np.nansum(subsys["penal_charge"] - base["penal_charge"], axis=1)
    last = lambda a: np.array([row[~np.isnan(row)][-1] if (~np.isnan(row)).any() else np.nan for row in a])
    att["interest_misstatement_inr"] = np.round(d_int, 2)
    att["penal_misstatement_inr"] = np.round(d_pen, 2)
    att["closing_balance_diff_inr"] = np.round(last(subsys["closing_balance"]) - last(base["closing_balance"]), 2)
    ex_counts = exc.groupby("loan_id")["period"].nunique()
    att["exception_periods"] = att["loan_id"].map(ex_counts).fillna(0).astype(int)
    first_last = exc.groupby("loan_id")["period"].agg(["min", "max"])
    att["first_exception_period"] = att["loan_id"].map(first_last["min"])
    att["last_exception_period"] = att["loan_id"].map(first_last["max"])

    # allocate rupee impact to controls (pairs: standalone impact of one leg, remainder to the other)
    alloc = []
    for j, r in att.iterrows():
        total = r.interest_misstatement_inr + r.penal_misstatement_inr
        if r.status != "Attributed":
            alloc.append({"loan_id": r.loan_id, "control_id": r.status.upper(), "impact_inr": total})
            continue
        ctrls = r.control_ids.split("+")
        if len(ctrls) == 1:
            alloc.append({"loan_id": r.loan_id, "control_id": ctrls[0], "impact_inr": total})
        else:
            legs = r.matching_hypotheses.split(" | ")[0].split(" + ")
            leg = next((l for l in legs if not l.startswith("C-01")), legs[0])
            lg = single_ledgers[leg]
            k = np.nonzero(sub.loan_id == r.loan_id)[0][0]
            a = float(np.nansum(lg["interest"][k] - base["interest"][k]) + np.nansum(lg["penal_charge"][k] - base["penal_charge"][k]))
            c_leg = leg[:4]
            other = [c for c in ctrls if c != c_leg][0]
            alloc += [{"loan_id": r.loan_id, "control_id": c_leg, "impact_inr": round(a, 2)},
                      {"loan_id": r.loan_id, "control_id": other, "impact_inr": round(total - a, 2)}]
    alloc = pd.DataFrame(alloc)

    # population-level differences (including sub-tolerance noise)
    both = ~np.isnan(exp["interest"]) & ~np.isnan(sys["interest"])
    pop_diff = {
        "total_expected_interest_inr": float(np.nansum(exp["interest"])),
        "total_system_interest_inr": float(np.nansum(np.where(both, sys["interest"], 0))),
        "total_interest_difference_inr": float(np.nansum(np.where(both, sys["interest"] - exp["interest"], 0))),
        "total_penal_difference_inr": float(np.nansum(np.where(both, sys["penal_charge"] - exp["penal_charge"], 0))),
    }
    timings["total_seconds"] = round(time.time() - t0, 2)

    expected_long(pop, exp).to_parquet(AUDIT_OUT / "expected_ledger.parquet", index=False)
    exc.to_parquet(AUDIT_OUT / "exceptions.parquet", index=False)
    exc.to_csv(AUDIT_OUT / "exceptions.csv", index=False)
    att.to_csv(AUDIT_OUT / "exception_loans_attribution.csv", index=False)
    alloc.to_csv(AUDIT_OUT / "impact_by_control.csv", index=False)
    log = {"timings": timings, "completeness": completeness, "population_differences": pop_diff,
           "tolerance": tol, "exception_rows": int(len(exc)),
           "exception_loan_periods": int(exc[["loan_id", "period"]].drop_duplicates().shape[0]),
           "exception_loans": int(len(exc_loans)),
           "attribution_status": att["status"].value_counts().to_dict()}
    (AUDIT_OUT / "run_log.json").write_text(json.dumps(log, indent=2, default=float), encoding="utf-8")
    print("\n=== Audit engine summary ===")
    print(f"Exception loan-periods: {log['exception_loan_periods']:,}; exception loans: {log['exception_loans']:,}")
    print("Attribution:", log["attribution_status"])
    print(alloc.groupby("control_id")["impact_inr"].agg(["count", "sum"]).round(0).to_string())
    print("Timings:", timings)
    return log


if __name__ == "__main__":
    main()
