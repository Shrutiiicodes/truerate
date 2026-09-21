"""ITAC work paper: interest computation on the loan book."""
from __future__ import annotations
import datetime as dt
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, PatternFill
from src.common.paths import OUTPUTS
from .xlsx_style import wp_header, table, text_block, INR, INT, PCT, base_font, INPUT_FONT, BORDER, HEADER_FILL
from openpyxl.styles import Font


def _hdr(ws, row, labels, widths=None):
    for j, l in enumerate(labels, start=1):
        c = ws.cell(row=row, column=j, value=l)
        c.font = Font(name="Arial", bold=True, color="FFFFFF", size=10); c.fill = HEADER_FILL; c.border = BORDER
        c.alignment = Alignment(wrap_text=True, vertical="center")
        if widths:
            ws.column_dimensions[c.column_letter].width = widths[j - 1]


def write_workpaper(r, cs, mat, detail, path=OUTPUTS / "workpaper_ITAC_interest.xlsx"):
    eng = r.cfg["engagement"]; tol = r.cfg["tolerance"]; comp = r.log["completeness"]
    wb = Workbook()

    # 1 Objective & Scope ---------------------------------------------------
    ws = wb.active; ws.title = "Objective & Scope"
    row = wp_header(ws, eng, "Objective & Scope", "1", ncols=3)
    text_block(ws, [
        ("Objective", "To obtain evidence that the core banking system (CBS) computes interest, penal charges and loan balances "
                      "in accordance with the approved product master and applicable RBI requirements, and that the related "
                      "automated application controls (ITACs) C-01 to C-09 operated effectively throughout the period."),
        ("Scope - systems", "Core banking system interest engine; product master (parameter tables); benchmark rate table."),
        ("Scope - population", f"All {comp['loans_in_master_file']:,} loan accounts across 5 products and all "
                               f"{comp['expected_loan_periods']:,} monthly billing periods from Jan-2021 to Jun-2025 (full population, no sampling)."),
        ("Approach", "Full-population independent recalculation instead of a test of one. A test of one gives comfort only if "
                     "ITGCs over the configuration are effective and the tested item is representative of every configuration "
                     "path. Recalculating every loan-period tests every product, convention, reset, moratorium, penal and closure "
                     "path directly and quantifies the error, so it does not depend on that inference."),
        ("Reliance on ITGC", "C-07 depends on ITGC change management over the product master. Other controls are automated; "
                             "the full-population recalculation reduces, but does not remove, the need for ITGC evidence over the period."),
        ("Tolerance", f"Exception where |system - recalculated| > max(INR {tol['absolute_inr']:.2f}, {tol['relative']:.2%} of recalculated), "
                      f"applied separately to interest, penal charge, closing principal and closing balance."),
        ("Data sources", "Loan master (contract terms), transaction file (disbursals, instalments, bounces, prepayments), "
                         "product master, RBI policy repo rate history, bank MCLR table (synthetic in this exercise), CBS interest ledger."),
        ("Data note", "All data is synthetic. No customer data is used."),
    ], row)

    # 2 Procedure performed ------------------------------------------------
    ws = wb.create_sheet("Procedure Performed")
    row = wp_header(ws, eng, "Procedure Performed", "2", ncols=4)
    steps = pd.DataFrame([
        (1, "Obtained CBS extracts (loan master, transactions, interest ledger) and product master; reconciled record counts and disbursed principal (tab 3).", "Population & Completeness"),
        (2, "Verified the repo rate table against RBI press releases / MPC statements for each change date.", "Reference data"),
        (3, "Independently recalculated every loan-period: rate from benchmark on reset date + spread + premium; accrual split into constant-balance/constant-rate segments; day-count per product; rounding once per period; simple (non-compounding) moratorium interest; fixed penal charge per bounced instalment; accrual stops on the closure value date.", "Recalculation"),
        (4, "Compared recalculated vs CBS interest, penal charge, closing principal and closing balance per loan-period against the tolerance; recorded every breach.", "Exceptions Detail"),
        (5, "For each exception loan, re-performed the calculation under each candidate configuration error (and pairs) and accepted a root cause only where it reproduced the CBS figures within tolerance for every period.", "Loan Attribution"),
        (6, "Quantified misstatement by control and compared the FY aggregate against overall, performance and clearly-trivial materiality.", "Materiality"),
        (7, "Concluded on each control (RCM) and drafted recommendations.", "Conclusion / RCM.xlsx"),
    ], columns=["Step", "Procedure", "Reference"])
    table(ws, steps, row, widths={"Step": 6, "Procedure": 110, "Reference": 26})
    for rr in range(row + 1, row + 1 + len(steps)):
        ws.cell(row=rr, column=2).alignment = Alignment(wrap_text=True, vertical="top"); ws.row_dimensions[rr].height = 45

    # 3 Population & completeness ------------------------------------------
    ws = wb.create_sheet("Population & Completeness")
    row = wp_header(ws, eng, "Population & Completeness", "3", ncols=7)
    _hdr(ws, row, ["Check", "Source A", "Count / amount A", "Source B", "Count / amount B", "Difference", "Result"],
         [34, 30, 20, 30, 20, 16, 14])
    checks = [
        ("Loans", "Loan master", comp["loans_in_master_file"], "CBS interest ledger (distinct loans)", comp["loans_in_system_ledger"]),
        ("Loans", "Loan master", comp["loans_in_master_file"], "Transaction file (distinct loans)", comp["loans_in_transactions"]),
        ("Loan-periods", "Expected from contract terms", comp["expected_loan_periods"], "CBS interest ledger rows", comp["system_ledger_rows"]),
        ("Disbursed principal (INR)", "Loan master", comp["disbursed_principal_master_inr"], "Transaction file - DISBURSAL", comp["disbursed_principal_transactions_inr"]),
        ("Ledger rows for unknown loans", "Expected", 0, "CBS interest ledger", comp["ledger_rows_for_unknown_loans"]),
    ]
    for k, (chk, sa, va, sb, vb) in enumerate(checks, start=row + 1):
        ws.cell(row=k, column=1, value=chk); ws.cell(row=k, column=2, value=sa)
        ws.cell(row=k, column=3, value=va).font = INPUT_FONT; ws.cell(row=k, column=4, value=sb)
        ws.cell(row=k, column=5, value=vb).font = INPUT_FONT
        ws.cell(row=k, column=6, value=f"=C{k}-E{k}")
        ws.cell(row=k, column=7, value=f'=IF(ABS(F{k})<0.005,"Reconciled","BREAK")')
        fmt = INR if "INR" in chk else INT
        for c in (3, 5, 6):
            ws.cell(row=k, column=c).number_format = fmt
    ws.cell(row=row + len(checks) + 2, column=1, value="Blue figures are extracted source values; differences and results are formulas.").font = base_font(size=9, italic=True)
    ws.cell(row=row + len(checks) + 3, column=1, value=f"Rows missing in CBS: {comp['rows_missing_in_system']}; extra rows in CBS: {comp['rows_extra_in_system']}.").font = base_font(size=9, italic=True)
    ws.freeze_panes = ws.cell(row=row + 1, column=1)

    # 4 Exceptions detail ----------------------------------------------------
    ws = wb.create_sheet("Exceptions Detail")
    row = wp_header(ws, eng, "Exceptions Detail (one row per loan-period breaching tolerance)", "4", ncols=len(detail.columns))
    money = {c: INR for c in detail.columns if any(x in c for x in ["interest_", "penal_", "balance", "_diff"])}
    table(ws, detail, row, formats=money, widths={"metrics_breached": 34, "root_cause_controls": 14, "attribution_status": 14})

    # 5 Loan attribution -----------------------------------------------------
    ws = wb.create_sheet("Loan Attribution")
    row = wp_header(ws, eng, "Root cause attribution by loan", "5", ncols=8)
    att = r.att[["loan_id", "product_code", "status", "control_ids", "matching_hypotheses", "implied_rate_offset_pct",
                 "exception_periods", "first_exception_period", "last_exception_period",
                 "interest_misstatement_inr", "penal_misstatement_inr", "closing_balance_diff_inr"]].copy()
    att["control_ids"] = att["control_ids"].fillna("")
    att["matching_hypotheses"] = att["matching_hypotheses"].fillna("")
    table(ws, att, row, formats={"interest_misstatement_inr": INR, "penal_misstatement_inr": INR, "closing_balance_diff_inr": INR,
                                 "exception_periods": INT}, widths={"matching_hypotheses": 48})
    la_first, la_last = row + 1, row + len(att)

    ws = wb.create_sheet("Impact Allocation")
    row = wp_header(ws, eng, "Rupee impact allocated to controls", "6", ncols=3)
    table(ws, r.alloc[["loan_id", "control_id", "impact_inr"]], row, formats={"impact_inr": INR})
    ia_first, ia_last = row + 1, row + len(r.alloc)

    # 6 Root cause summary ---------------------------------------------------
    ws = wb.create_sheet("Root Cause Summary")
    row = wp_header(ws, eng, "Root Cause Summary", "7", ncols=7)
    _hdr(ws, row, ["Control ID", "Control", "Loans attributed", "Exception loan-periods", "Net impact (INR)", "Gross impact (INR)", "Conclusion"],
         [11, 34, 16, 20, 20, 20, 14])
    LA, IA, ED = "'Loan Attribution'", "'Impact Allocation'", "'Exceptions Detail'"
    ed_last = 6 + len(detail)
    k = row
    for k, c in enumerate(cs.itertuples(), start=row + 1):
        ws.cell(row=k, column=1, value=c.control_id); ws.cell(row=k, column=2, value=c.control_name)
        ws.cell(row=k, column=3, value=f'=COUNTIFS({LA}!$D${la_first}:$D${la_last},"*"&A{k}&"*",{LA}!$C${la_first}:$C${la_last},"Attributed")')
        ws.cell(row=k, column=4, value=f'=COUNTIFS({ED}!$D$7:$D${ed_last},"*"&A{k}&"*")')
        ws.cell(row=k, column=5, value=f"=SUMIFS({IA}!$C${ia_first}:$C${ia_last},{IA}!$B${ia_first}:$B${ia_last},A{k})")
        ws.cell(row=k, column=6, value=c.impact_gross_window_inr).font = INPUT_FONT
        ws.cell(row=k, column=7, value=f'=IF(C{k}>0,"Deficient","Effective")')
    last_c = k
    for k2, status in enumerate(["UNEXPLAINED", "AMBIGUOUS"], start=last_c + 1):
        ws.cell(row=k2, column=1, value=status); ws.cell(row=k2, column=2, value="Open item - manual follow-up" if status == "UNEXPLAINED" else "Several hypotheses fit")
        ws.cell(row=k2, column=3, value=f'=COUNTIFS({LA}!$C${la_first}:$C${la_last},"{status.title()}")')
        ws.cell(row=k2, column=5, value=f"=SUMIFS({IA}!$C${ia_first}:$C${ia_last},{IA}!$B${ia_first}:$B${ia_last},A{k2})")
    tot = last_c + 3
    ws.cell(row=tot, column=2, value="Total").font = base_font(True)
    for col in "CE":
        ws[f"{col}{tot}"] = f"=SUM({col}{row + 1}:{col}{tot - 1})"; ws[f"{col}{tot}"].font = base_font(True)
    ws[f"F{tot}"] = f"=SUM(F{row + 1}:F{last_c})"; ws[f"F{tot}"].font = base_font(True)
    for rr in range(row + 1, tot + 1):
        for col in "EF":
            ws[f"{col}{rr}"].number_format = INR
        for col in "CD":
            ws[f"{col}{rr}"].number_format = INT
    ws.cell(row=tot + 2, column=1, value="Loans with two attributed controls are counted under each control (column C); rupee impact is allocated without double counting (column E).").font = base_font(size=9, italic=True)
    ws.cell(row=tot + 3, column=1, value="Gross impact (blue) = sum of absolute per-loan allocations, from the engine output.").font = base_font(size=9, italic=True)
    ws.freeze_panes = ws.cell(row=row + 1, column=1)

    # 7 Materiality ----------------------------------------------------------
    ws = wb.create_sheet("Materiality")
    row = wp_header(ws, eng, f"Materiality - {mat['fy_label']}", "8", ncols=3)
    ws.column_dimensions["A"].width = 58; ws.column_dimensions["B"].width = 22; ws.column_dimensions["C"].width = 60
    rows = [
        ("Basis: recalculated interest income, " + mat["fy_label"], mat["basis_interest_income"], INR, True, "Sum of recalculated interest for FY loan-periods"),
        ("Overall materiality %", mat["overall_pct"], PCT, True, "Illustrative - per audit.yaml; real engagements take this from the planning memo"),
        ("Overall materiality", "=B7*B8", INR, False, ""),
        ("Performance materiality % of overall", mat["pm_pct"], PCT, True, ""),
        ("Performance materiality", "=B9*B10", INR, False, ""),
        ("Clearly trivial % of overall", mat["ct_pct"], PCT, True, ""),
        ("Clearly trivial threshold", "=B9*B12", INR, False, ""),
        ("", None, None, False, ""),
        ("Net misstatement in FY (system - recalculated; interest + penal)", mat["fy_net_misstatement"], INR, True, "All FY loan-periods, including sub-tolerance differences"),
        ("Gross misstatement in FY (absolute)", mat["fy_gross_misstatement"], INR, True, "Offsetting errors do not cancel"),
        ("Net misstatement as % of overall materiality", "=B15/B9", PCT, False, ""),
        ("Material? (|net| >= overall materiality)", '=IF(ABS(B15)>=B9,"MATERIAL","Not material")', None, False, ""),
        ("Exceeds performance materiality?", '=IF(ABS(B15)>=B11,"Yes","No")', None, False, ""),
        ("Above clearly trivial? (accumulate on summary of audit differences)", '=IF(ABS(B15)>=B13,"Yes - record on SAD","No")', None, False, ""),
    ]
    for k, (lab, val, fmt, is_input, note) in enumerate(rows, start=7):
        ws.cell(row=k, column=1, value=lab).font = base_font(bool(lab) and not is_input)
        if val is not None:
            c = ws.cell(row=k, column=2, value=val)
            c.font = INPUT_FONT if is_input else base_font(True)
            if fmt: c.number_format = fmt
        ws.cell(row=k, column=3, value=note).font = base_font(size=9, italic=True)
    ws.cell(row=6, column=1, value="Item").font = base_font(True); ws.cell(row=6, column=2, value="Value").font = base_font(True)
    k = 7 + len(rows) + 1
    ws.cell(row=k, column=1, value="FY misstatement by control").font = base_font(True)
    _hdr(ws, k + 1, ["Control", "Net (INR)", "Gross (INR)"])
    pc = mat["per_control"]
    for j, (c, v) in enumerate(pc.iterrows(), start=k + 2):
        ws.cell(row=j, column=1, value=c); ws.cell(row=j, column=2, value=float(v["net"])).number_format = INR
        ws.cell(row=j, column=3, value=float(v["gross"])).number_format = INR
    j = k + 2 + len(pc)
    ws.cell(row=j, column=1, value="Total attributed").font = base_font(True)
    ws.cell(row=j, column=2, value=f"=SUM(B{k + 2}:B{j - 1})").number_format = INR
    ws.cell(row=j, column=3, value=f"=SUM(C{k + 2}:C{j - 1})").number_format = INR

    # 8 Conclusion -----------------------------------------------------------
    ws = wb.create_sheet("Conclusion")
    row = wp_header(ws, eng, "Conclusion", "9", ncols=3)
    deficient = cs[cs.conclusion == "Deficient"]
    sig = cs[cs.deficiency_classification.str.startswith("Significant")]
    n_unexp = int((r.att.status == "Unexplained").sum()); n_amb = int((r.att.status == "Ambiguous").sum())
    verdict = "is NOT material" if not mat["is_material"] else "IS MATERIAL"
    end = text_block(ws, [
        ("Overall conclusion", f"{len(deficient)} of {len(cs)} automated controls tested are DEFICIENT. "
                               f"{r.log['exception_loans']:,} loans ({r.log['exception_loans'] / comp['loans_in_master_file']:.2%} of the population) "
                               f"and {r.log['exception_loan_periods']:,} loan-periods breached tolerance. The aggregate {mat['fy_label']} net misstatement of "
                               f"INR {mat['fy_net_misstatement']:,.0f} {verdict} (overall materiality INR {mat['overall_materiality']:,.0f}; "
                               f"performance materiality INR {mat['performance_materiality']:,.0f})."),
        ("Why deficient but not material", "Each fault affects a small group of accounts, so the income effect is small relative to the portfolio. "
                                           "Control conclusions are driven by the existence of systematic configuration errors, not only by rupee size: "
                                           "every one of these errors would recur on new accounts until fixed."),
        ("Significant deficiencies", "; ".join(f"{x.control_id} {x.control_name}" for x in sig.itertuples()) +
                                     ". Escalated on qualitative grounds: EBLR reset timing and the penal-charge circular are regulatory requirements; "
                                     "C-07 points to an ITGC change-management failure, which may affect other parameter changes not covered by this test."),
        ("Open items", f"{n_unexp} unexplained and {n_amb} ambiguous exception loan(s) referred for manual investigation with the client."),
        ("Impact on audit approach", "Do not rely on the ITACs for the period. Extend ITGC testing (change management over the product master), "
                                     "request management's root-cause analysis and remediation, and record the FY difference on the summary of audit differences."),
        ("Customer impact", "Where the net effect is positive customers were overcharged; refunds and regulatory reporting should be considered by management."),
    ], row)
    s = end + 2
    ws.cell(row=s, column=1, value="Sign-off").font = base_font(True, 11)
    _hdr(ws, s + 1, ["Role", "Name", "Date"], [28, 60, 20])
    for k, (role, name) in enumerate([("Prepared by", eng["prepared_by"]), ("Reviewed by", eng["reviewed_by"]), ("Partner review", "")], start=s + 2):
        ws.cell(row=k, column=1, value=role).font = base_font(True)
        ws.cell(row=k, column=2, value=name).font = INPUT_FONT
        ws.cell(row=k, column=3, value=dt.date.today().isoformat() if role == "Prepared by" else "").font = INPUT_FONT
        for c in (1, 2, 3):
            ws.cell(row=k, column=c).border = BORDER
    wb.save(path)
    return path
