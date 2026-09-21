"""Stage 6 driver: RCM, work paper, materiality summary, Power BI exports, charts."""
from __future__ import annotations
import time
from src.common.paths import OUTPUTS
from .summary import load_results, period_differences, control_period_impact, materiality, control_summary, loan_period_detail
from .rcm import write_rcm
from .workpaper import write_workpaper
from .powerbi import write_powerbi
from .charts import write_charts


def write_materiality_md(mat, cs):
    L = [f"# Materiality summary - {mat['fy_label']}", "",
         "| Item | INR |", "|---|---|",
         f"| Basis: recalculated interest income | {mat['basis_interest_income']:,.2f} |",
         f"| Overall materiality ({mat['overall_pct']:.2%} of basis) | {mat['overall_materiality']:,.2f} |",
         f"| Performance materiality ({mat['pm_pct']:.0%} of overall) | {mat['performance_materiality']:,.2f} |",
         f"| Clearly trivial ({mat['ct_pct']:.0%} of overall) | {mat['clearly_trivial']:,.2f} |",
         f"| Net misstatement in FY | {mat['fy_net_misstatement']:,.2f} |",
         f"| Gross misstatement in FY | {mat['fy_gross_misstatement']:,.2f} |", "",
         f"**Conclusion:** net misstatement is {abs(mat['fy_net_misstatement']) / mat['overall_materiality']:.1%} of overall materiality - "
         f"{'MATERIAL' if mat['is_material'] else 'not material'}; "
         f"{'above' if mat['above_ct'] else 'below'} clearly trivial, so it is recorded on the summary of audit differences.", "",
         "Materiality is illustrative (allocated to this portfolio as a % of its interest income). Control conclusions do not "
         "depend on it: a systematic configuration error is a deficiency whatever its current rupee size.", "",
         "| Control | Net FY (INR) | Gross FY (INR) | Classification |", "|---|---|---|---|"]
    for c in cs.itertuples():
        L.append(f"| {c.control_id} {c.control_name} | {c.impact_net_fy_inr:,.2f} | {c.impact_gross_fy_inr:,.2f} | {c.deficiency_classification} |")
    (OUTPUTS / "materiality_summary.md").write_text("\n".join(L))


def main():
    t0 = time.time()
    r = load_results()
    pdiff = period_differences(r)
    cpi = control_period_impact(r, pdiff)
    mat = materiality(r, pdiff, cpi)
    cs = control_summary(r, mat)
    cs.to_csv(OUTPUTS / "audit" / "control_summary.csv", index=False)
    detail = loan_period_detail(r)
    write_rcm(cs, r.cfg["engagement"], int((r.att.status == "Unexplained").sum()))
    write_workpaper(r, cs, mat, detail)
    write_materiality_md(mat, cs)
    pb = write_powerbi(r, cs)
    charts = write_charts(r, cs, mat)
    print(f"[reporting] RCM.xlsx, workpaper_ITAC_interest.xlsx, materiality_summary.md, Power BI {pb}, {len(charts)} charts "
          f"in {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
