"""Static PNG charts for the README and the work paper."""
from __future__ import annotations
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from src.common.paths import OUTPUTS

CH = OUTPUTS / "charts"
NAVY, RED, GREY = "#1F3864", "#C0504D", "#A6A6A6"


def _style(ax, title):
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color=NAVY)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.grid(axis="y", alpha=0.3)


def write_charts(r, cs, mat) -> list:
    CH.mkdir(parents=True, exist_ok=True)
    out = []
    # 1 exception loans by control
    fig, ax = plt.subplots(figsize=(9, 4.5))
    ax.bar(cs.control_id + "\n" + cs.control_name.str.split(" ").str[0], cs.loans_with_exceptions, color=NAVY)
    for i, v in enumerate(cs.loans_with_exceptions):
        ax.text(i, v + 2, f"{v}", ha="center", fontsize=8)
    _style(ax, "Loans with exceptions by control"); ax.set_ylabel("Loans"); ax.tick_params(axis="x", labelsize=8)
    fig.tight_layout(); p = CH / "exceptions_by_control.png"; fig.savefig(p, dpi=150); plt.close(fig); out.append(p)

    # 2 rupee impact net vs gross
    fig, ax = plt.subplots(figsize=(9, 4.5))
    x = np.arange(len(cs)); w = 0.4
    ax.bar(x - w / 2, cs.impact_net_window_inr / 1e5, w, label="Net", color=NAVY)
    ax.bar(x + w / 2, cs.impact_gross_window_inr / 1e5, w, label="Gross", color=GREY)
    ax.axhline(0, color="black", lw=0.8); ax.set_xticks(x, cs.control_id)
    _style(ax, "Rupee impact by control, Jan-2021 to Jun-2025 (INR lakh)"); ax.legend(frameon=False)
    fig.tight_layout(); p = CH / "impact_by_control.png"; fig.savefig(p, dpi=150); plt.close(fig); out.append(p)

    # 3 trend: exception loan-periods per month by control
    lp = r.exc[["loan_id", "period"]].drop_duplicates()
    ctrl = r.att.set_index("loan_id")["control_ids"].fillna("UNEXPLAINED")
    lp["ctrl"] = lp["loan_id"].map(ctrl).str.split("+").str[0]
    piv = lp.pivot_table(index="period", columns="ctrl", values="loan_id", aggfunc="count", fill_value=0).sort_index()
    fig, ax = plt.subplots(figsize=(10, 4.8))
    ax.stackplot(range(len(piv)), piv.T.values, labels=piv.columns, alpha=0.9)
    ticks = list(range(0, len(piv), 6)); ax.set_xticks(ticks, piv.index[ticks], rotation=0, fontsize=8)
    _style(ax, "Exception loan-periods per billing month (by primary root cause)")
    ax.legend(ncol=5, fontsize=7, frameon=False, loc="upper left")
    fig.tight_layout(); p = CH / "exceptions_trend.png"; fig.savefig(p, dpi=150); plt.close(fig); out.append(p)

    # 4 repo rate with MCLR
    b = r.raw["master"]  # noqa - kept for symmetry
    from src.common.io import load_table
    bench = load_table("benchmark_rates")
    fig, ax = plt.subplots(figsize=(9, 3.8))
    for name, col in [("REPO", NAVY), ("MCLR_1Y", RED)]:
        g = bench[bench.benchmark == name].copy()
        d = pd.to_datetime(g.effective_date)
        d = pd.concat([d, pd.Series([pd.Timestamp("2025-06-30")])], ignore_index=True)
        v = list(g.rate_pct) + [g.rate_pct.iloc[-1]]
        ax.step(d, v, where="post", color=col, label="RBI repo rate" if name == "REPO" else "1Y MCLR (synthetic)")
    ax.set_xlim(pd.Timestamp("2021-01-01"), pd.Timestamp("2025-06-30"))
    _style(ax, "Benchmarks used in recalculation (% p.a.)"); ax.legend(frameon=False)
    fig.tight_layout(); p = CH / "benchmark_rates.png"; fig.savefig(p, dpi=150); plt.close(fig); out.append(p)

    # 5 materiality
    fig, ax = plt.subplots(figsize=(8, 3.6))
    labels = ["Net misstatement", "Clearly trivial", "Performance mat.", "Overall mat."]
    vals = [abs(mat["fy_net_misstatement"]), mat["clearly_trivial"], mat["performance_materiality"], mat["overall_materiality"]]
    ax.barh(labels, np.array(vals) / 1e5, color=[RED, GREY, GREY, NAVY])
    for i, v in enumerate(vals):
        ax.text(v / 1e5, i, f"  {v / 1e5:,.1f}", va="center", fontsize=8)
    _style(ax, f"{mat['fy_label']} misstatement vs materiality (INR lakh)"); ax.grid(axis="x", alpha=0.3)
    fig.tight_layout(); p = CH / "materiality.png"; fig.savefig(p, dpi=150); plt.close(fig); out.append(p)
    return out
