"""ITAC interest testing - results viewer.

Run:  streamlit run app/streamlit_app.py   (after `python run_all.py`)
"""
from __future__ import annotations
import streamlit as st
import pandas as pd
import data as D

st.set_page_config(page_title="ITAC - Loan interest testing", layout="wide")


@st.cache_data
def _load():
    return D.run_log(), D.control_summary(), D.attribution(), D.exceptions()


log, cs, att, exc = _load()
page = st.sidebar.radio("View", ["Overview", "Risk & Control Matrix", "Exceptions", "Loan drill-down", "Evaluation"])
st.sidebar.caption("Synthetic data. Audit engine never reads ground truth; the Evaluation page is the only view that uses it.")

if page == "Overview":
    st.title("ITAC - Loan interest computation")
    c = log["completeness"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Loans tested", f"{c['loans_in_master_file']:,}")
    k2.metric("Loan-periods recalculated", f"{c['expected_loan_periods']:,}")
    k3.metric("Exception loans", f"{log['exception_loans']:,}", f"{log['exception_loans'] / c['loans_in_master_file']:.2%} of population",
              delta_color="off")
    k4.metric("Full-population runtime", f"{log['timings']['total_seconds']:.1f}s")
    st.subheader("Conclusions by control")
    st.dataframe(cs[["control_id", "control_name", "population_size", "loans_with_exceptions", "exception_loan_periods",
                     "impact_net_window_inr", "conclusion", "deficiency_classification"]], use_container_width=True, hide_index=True)
    left, right = st.columns(2)
    for col, img in [(left, "exceptions_by_control.png"), (right, "impact_by_control.png")]:
        p = D.OUT / "charts" / img
        if p.exists():
            col.image(str(p))
    p = D.OUT / "charts" / "exceptions_trend.png"
    if p.exists():
        st.image(str(p))

elif page == "Risk & Control Matrix":
    st.title("Risk & Control Matrix")
    ctrl = st.selectbox("Control", cs["control_id"] + " - " + cs["control_name"])
    row = cs[cs["control_id"] == ctrl[:4]].iloc[0]
    for label, key in [("Risk", "risk"), ("Control", "control_description"), ("Type", "control_type"),
                       ("Test procedure", "test_procedure"), ("Population", "population_description"),
                       ("Recommendation", "recommendation")]:
        st.markdown(f"**{label}:** {row[key]}")
    a, b, c3 = st.columns(3)
    a.metric("Population size", f"{int(row['population_size']):,}")
    b.metric("Loans with exceptions", f"{int(row['loans_with_exceptions']):,}")
    c3.metric("Net impact (INR)", f"{row['impact_net_window_inr']:,.0f}")
    st.markdown(f"**Conclusion:** {row['conclusion']} - {row['deficiency_classification']}")
    st.divider()
    st.dataframe(cs, use_container_width=True, hide_index=True)

elif page == "Exceptions":
    st.title("Exceptions")
    f1, f2, f3 = st.columns(3)
    controls = sorted({c for s in exc["root_cause"].dropna() for c in s.split("+")})
    sel_c = f1.multiselect("Root-cause control", controls)
    sel_p = f2.multiselect("Product", sorted(exc["product_code"].unique()))
    sel_m = f3.multiselect("Metric", sorted(exc["metric"].unique()))
    view = exc
    if sel_c:
        view = view[view["root_cause"].apply(lambda s: any(c in s.split("+") for c in sel_c))]
    if sel_p:
        view = view[view["product_code"].isin(sel_p)]
    if sel_m:
        view = view[view["metric"].isin(sel_m)]
    st.caption(f"{len(view):,} exception rows | {view['loan_id'].nunique():,} loans | "
               f"interest difference INR {view.loc[view.metric == 'interest', 'difference_inr'].sum():,.2f}")
    st.dataframe(view.head(5000), use_container_width=True, hide_index=True)
    st.download_button("Download filtered exceptions (CSV)", view.to_csv(index=False), "exceptions_filtered.csv")

elif page == "Loan drill-down":
    st.title("Loan drill-down")
    default = att.sort_values("interest_misstatement_inr", key=abs, ascending=False)["loan_id"].tolist()
    loan = st.selectbox("Exception loan (sorted by rupee impact)", default)
    typed = st.text_input("...or type any loan ID", "")
    loan = typed.strip() or loan
    info = D.loan_contract(loan)
    if not info:
        st.error("Loan not found")
    else:
        a = att[att["loan_id"] == loan]
        st.markdown(f"**{loan}** - {info['product_code']}, disbursed {info['disbursal_date']}, principal INR "
                    f"{info['principal_inr']:,.0f}, tenure {info['tenure_months']}m, moratorium {info['moratorium_months']}m")
        if len(a):
            r = a.iloc[0]
            st.info(f"Status: {r['status']} | Root cause: {r['control_ids'] if pd.notna(r['control_ids']) else '-'} | "
                    f"Hypothesis: {r['matching_hypotheses'] if pd.notna(r['matching_hypotheses']) else '-'}")
        else:
            st.success("No exceptions on this loan.")
        d = D.loan_drilldown(loan)
        metric = st.radio("Metric", ["interest", "closing_balance", "closing_principal", "penal_charge"], horizontal=True)
        st.line_chart(d.set_index("period")[[f"{metric}_expected", f"{metric}_system"]])
        st.bar_chart(d.set_index("period")[f"{metric}_diff"])
        st.dataframe(d, use_container_width=True, hide_index=True)

else:
    st.title("Evaluation against injected ground truth")
    ev = D.evaluation_json()
    if ev:
        d = ev["detection_vs_any_change"]["loan_level"]; at = ev["attribution"]
        k1, k2, k3 = st.columns(3)
        k1.metric("Loan-level precision", f"{d['precision']:.1%}")
        k2.metric("Loan-level recall", f"{d['recall']:.1%}")
        k3.metric("Attribution accuracy", f"{at['exact_match_accuracy']:.1%}")
        st.subheader("Tolerance sensitivity")
        st.line_chart(pd.DataFrame(ev["tolerance_sensitivity"]).set_index("abs_tolerance_inr")[["loan_recall", "lp_recall", "lp_precision"]])
    st.markdown(D.evaluation_markdown())
