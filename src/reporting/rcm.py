"""Risk and Control Matrix workbook."""
from __future__ import annotations
from openpyxl import Workbook
from openpyxl.styles import Alignment, PatternFill
from src.common.paths import OUTPUTS
from .xlsx_style import wp_header, table, INR, INT, base_font

COLS = {"control_id": "Control ID", "control_name": "Control", "process": "Process", "risk": "Risk",
        "control_description": "Control description", "control_type": "Control type", "test_procedure": "Test procedure",
        "population_description": "Population tested", "population_size": "Population size",
        "loans_with_exceptions": "Loans with exceptions", "exception_loan_periods": "Exception loan-periods",
        "impact_net_window_inr": "Rupee impact - net, full window (INR)", "impact_gross_fy_inr": "Rupee impact - gross, FY (INR)",
        "conclusion": "Conclusion", "deficiency_classification": "Deficiency classification", "recommendation": "Recommendation"}


def write_rcm(cs, eng, unexplained: int, path=OUTPUTS / "RCM.xlsx"):
    wb = Workbook(); ws = wb.active; ws.title = "RCM"
    r0 = wp_header(ws, eng, "Risk and Control Matrix", "RCM", ncols=len(COLS))
    df = cs[list(COLS)].rename(columns=COLS)
    widths = {"Control ID": 9, "Control": 20, "Process": 18, "Risk": 45, "Control description": 40, "Control type": 16,
              "Test procedure": 45, "Population tested": 30, "Recommendation": 50, "Deficiency classification": 28}
    first, last = table(ws, df, r0, formats={"Population size": INT, "Loans with exceptions": INT, "Exception loan-periods": INT,
                                             "Rupee impact - net, full window (INR)": INR, "Rupee impact - gross, FY (INR)": INR},
                        widths=widths)
    red, green = PatternFill("solid", fgColor="F8CBAD"), PatternFill("solid", fgColor="C6EFCE")
    concl_col = list(COLS.values()).index("Conclusion") + 1
    for r in range(first, last + 1):
        ws.row_dimensions[r].height = 90
        for c in range(1, len(COLS) + 1):
            ws.cell(row=r, column=c).alignment = Alignment(wrap_text=True, vertical="top")
        cell = ws.cell(row=r, column=concl_col)
        cell.fill = red if cell.value == "Deficient" else green
    t = last + 1
    ws.cell(row=t, column=1, value="Total").font = base_font(True)
    for name in ["Loans with exceptions", "Exception loan-periods", "Rupee impact - net, full window (INR)", "Rupee impact - gross, FY (INR)"]:
        j = list(COLS.values()).index(name) + 1
        col = ws.cell(row=first, column=j).column_letter
        c = ws.cell(row=t, column=j, value=f"=SUM({col}{first}:{col}{last})")
        c.font = base_font(True); c.number_format = INR if "INR" in name else INT
    n = t + 2
    ws.cell(row=n, column=1, value="Notes").font = base_font(True)
    notes = [f"Open item: {unexplained} exception loan(s) could not be attributed to any hypothesis or pair - referred for manual follow-up (see work paper, Loan Attribution tab).",
             "Loans attributed to two controls are counted under both controls; rupee impact is split between them (standalone impact of one leg, remainder to the other), so totals do not double count.",
             "Net impact = system minus recalculated (positive = income overstated / customers overcharged). Gross = sum of absolute differences.",
             "Conclusion 'Deficient' where at least one exception is attributed to the control. Classification follows audit.yaml (quantitative vs FY materiality, qualitative escalation for regulatory/ITGC-linked controls)."]
    for k, s in enumerate(notes, start=1):
        c = ws.cell(row=n + k, column=1, value=s); c.font = base_font(size=9, italic=True)
    wb.save(path)
    return path
