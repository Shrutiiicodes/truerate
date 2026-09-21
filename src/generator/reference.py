"""Stage 1: benchmark reference data.

REPO: RBI policy repo rate changes (verified against RBI press releases /
MPC statements). 27-Mar-2020 row included so that lookups before 22-May-2020 work.
MCLR_1Y: SYNTHETIC. There is no single 'MCLR' - each bank sets its own. We model a
representative bank's 1-year MCLR as a lagged, damped function of the repo rate:
    MCLR_1Y(month) = 7.00 + 0.65 * (repo in force 90 days earlier - 4.00), rounded to 5 bps,
reset on the 1st of each month.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from src.common.paths import REFERENCE
from src.common.rates import StepCurve
from src.common.calendar import to_days

REPO_CHANGES = [
    ("2020-03-27", 4.40, "Off-cycle MPC, 27-Mar-2020 (context row; pre-window)"),
    ("2020-05-22", 4.00, "Off-cycle MPC, 22-May-2020"),
    ("2022-05-04", 4.40, "Off-cycle MPC, 04-May-2022"),
    ("2022-06-08", 4.90, "MPC, 08-Jun-2022"),
    ("2022-08-05", 5.40, "MPC, 05-Aug-2022"),
    ("2022-09-30", 5.90, "MPC, 30-Sep-2022"),
    ("2022-12-07", 6.25, "MPC, 07-Dec-2022"),
    ("2023-02-08", 6.50, "MPC, 08-Feb-2023"),
    ("2025-02-07", 6.25, "MPC, 07-Feb-2025"),
    ("2025-04-09", 6.00, "MPC, 09-Apr-2025"),
    ("2025-06-06", 5.50, "MPC, 06-Jun-2025"),
]
MCLR_BASE, MCLR_BETA, MCLR_LAG_DAYS = 7.00, 0.65, 90


def build_benchmarks() -> pd.DataFrame:
    repo = pd.DataFrame(REPO_CHANGES, columns=["effective_date", "rate_pct", "source"])
    repo.insert(0, "benchmark", "REPO")
    curve = StepCurve(to_days(repo["effective_date"]), repo["rate_pct"].values)
    months = pd.date_range("2020-07-01", "2025-06-01", freq="MS")
    lagged = curve.at(to_days(months.values) - MCLR_LAG_DAYS)
    mclr = np.round((MCLR_BASE + MCLR_BETA * (lagged - 4.00)) / 0.05) * 0.05
    m = pd.DataFrame({"benchmark": "MCLR_1Y", "effective_date": months.strftime("%Y-%m-%d"),
                      "rate_pct": np.round(mclr, 2), "source": "SYNTHETIC - lagged/damped repo proxy"})
    m = m[m["rate_pct"].diff().fillna(1) != 0]          # keep change points only
    return pd.concat([repo, m], ignore_index=True)


def write_benchmarks() -> pd.DataFrame:
    df = build_benchmarks()
    REFERENCE.mkdir(parents=True, exist_ok=True)
    df.to_csv(REFERENCE / "benchmark_rates.csv", index=False)
    return df


if __name__ == "__main__":
    print(write_benchmarks().to_string())
