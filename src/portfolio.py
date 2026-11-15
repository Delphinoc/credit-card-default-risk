"""Portfolio monitoring: delinquency buckets, roll rates and a one-page KPI dashboard.

Usage:  python src/portfolio.py
Builds on the SQL pipeline (01-03), runs sql/04_portfolio.sql, stops if a blocking
portfolio check fails, exports the marts to outputs/portfolio/ (ready to load into
Power BI or Tableau) and draws reports/figures/portfolio_dashboard.png.
"""
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

import pipeline  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "portfolio"
FIG = ROOT / "reports" / "figures"

PORTFOLIO_MARTS = [
    "mart_portfolio_monthly",
    "mart_roll_rates",
    "mart_roll_rates_monthly",
    "mart_bucket_to_default",
    "mart_segment_delinquency",
    "dq_portfolio",
]

GREY, ACCENT, DARK = "#9AA5B1", "#C8102E", "#1F2933"
MONTHS = ["Apr", "May", "Jun", "Jul", "Aug", "Sep"]


def build(con: duckdb.DuckDBPyConnection | None = None) -> duckdb.DuckDBPyConnection:
    con = con or pipeline.build()
    pipeline.run_sql(con, "04_portfolio.sql")
    dq = con.sql("SELECT * FROM dq_portfolio").df()
    failed = dq[(dq.severity == "error") & (dq.violations > 0)]
    if not failed.empty:
        raise pipeline.DataQualityError(f"Blocking portfolio checks failed:\n{failed}")
    OUT.mkdir(parents=True, exist_ok=True)
    for m in PORTFOLIO_MARTS:
        con.sql(f"SELECT * FROM {m}").df().to_csv(OUT / f"{m}.csv", index=False)
    return con


def kpis(con) -> dict:
    m = con.sql("SELECT * FROM mart_portfolio_monthly ORDER BY statement_month").df()
    b = con.sql("SELECT * FROM mart_bucket_to_default ORDER BY sep_bucket").df()
    r = con.sql("SELECT * FROM mart_roll_rates").df()
    cur = r[r.from_bucket == "0. current"].set_index("to_bucket").roll_rate
    late = r[r.from_bucket == "1. 1-2 months late"].set_index("to_bucket").roll_rate
    sep, apr = m.iloc[-1], m.iloc[0]
    late_sep = b[b.sep_bucket != "0. current"]
    return {
        "outstanding_sep_ntd_m": round(sep.outstanding_ntd / 1e6, 1),
        "outstanding_growth_apr_sep": round(sep.outstanding_ntd / apr.outstanding_ntd - 1, 4),
        "utilisation_apr": float(apr.portfolio_utilisation),
        "utilisation_sep": float(sep.portfolio_utilisation),
        "dq2plus_peak_month": m.loc[m.dq2plus_rate_accounts.idxmax(), "statement_month"],
        "dq2plus_peak_rate": float(m.dq2plus_rate_accounts.max()),
        "dq2plus_apr": float(apr.dq2plus_rate_accounts),
        "dq1plus_sep": float(sep.dq1plus_rate_accounts),
        "roll_current_to_late": round(1 - cur.get("0. current", 0), 4),
        "roll_late12_to_3plus": float(late.get("2. 3+ months late", 0)),
        "cure_late12": float(late.get("0. current", 0)),
        "late_sep_accounts_share": round(late_sep.accounts.sum() / b.accounts.sum(), 4),
        "late_sep_defaults_share": round(late_sep.defaults.sum() / b.defaults.sum(), 4),
        "default_rate_current_sep": float(b.loc[b.sep_bucket == "0. current", "default_rate"].iloc[0]),
        "default_rate_late12_sep": float(b.loc[b.sep_bucket == "1. 1-2 months late", "default_rate"].iloc[0]),
        "default_rate_3plus_sep": float(b.loc[b.sep_bucket == "2. 3+ months late", "default_rate"].iloc[0]),
    }


def dashboard(con, k: dict, path: Path = FIG / "portfolio_dashboard.png") -> Path:
    m = con.sql("SELECT * FROM mart_portfolio_monthly ORDER BY statement_month").df()
    rm = con.sql("SELECT * FROM mart_roll_rates_monthly ORDER BY month_pair").df()
    r = con.sql("SELECT * FROM mart_roll_rates").df()
    b = con.sql("SELECT * FROM mart_bucket_to_default ORDER BY sep_bucket").df()
    s = con.sql("SELECT * FROM mart_segment_delinquency WHERE dimension='credit_limit' ORDER BY segment").df()

    fig = plt.figure(figsize=(14, 9.5))
    gs = fig.add_gridspec(3, 6, height_ratios=[0.55, 1, 1], hspace=0.55, wspace=0.9)
    fig.suptitle("Credit card portfolio monitor  |  30,000 accounts, Apr-Sep 2005 (UCI, NT$)",
                 x=0.06, ha="left", fontsize=15, fontweight="bold", color=DARK)

    tiles = [
        ("Outstanding (Sep)", f"NT${k['outstanding_sep_ntd_m']:,.0f}M",
         f"+{k['outstanding_growth_apr_sep']:.0%} since Apr"),
        ("Utilisation (Sep)", f"{k['utilisation_sep']:.1%}", f"from {k['utilisation_apr']:.1%} in Apr"),
        ("2+ months late (peak)", f"{k['dq2plus_peak_rate']:.1%}",
         f"in {MONTHS[int(k['dq2plus_peak_month'][-2:]) - 4]}; {k['dq2plus_apr']:.1%} in Apr"),
        ("Current -> late / month", f"{k['roll_current_to_late']:.1%}", "avg, Apr-Aug"),
        ("Late -> 3+ / month", f"{k['roll_late12_to_3plus']:.1%}",
         f"cure rate {k['cure_late12']:.0%}"),
        ("Late in Sep -> share of defaults", f"{k['late_sep_defaults_share']:.0%}",
         f"from {k['late_sep_accounts_share']:.0%} of accounts"),
    ]
    for i, (label, value, sub) in enumerate(tiles):
        ax = fig.add_subplot(gs[0, i]); ax.axis("off")
        ax.text(0, 0.95, label, fontsize=9, color="#52606D", va="top")
        ax.text(0, 0.55, value, fontsize=17, fontweight="bold", color=ACCENT if i >= 2 else DARK, va="top")
        ax.text(0, 0.05, sub, fontsize=8.5, color="#52606D", va="top")

    # Delinquency trend
    ax = fig.add_subplot(gs[1, 0:3])
    ax.plot(MONTHS, m.dq2plus_rate_accounts * 100, marker="o", color=ACCENT, label="2+ months late (accounts)")
    ax.plot(MONTHS, m.dq2plus_rate_balance * 100, marker="o", color=ACCENT, ls="--", alpha=0.6,
            label="2+ months late (balance)")
    ax.plot(MONTHS, m.portfolio_utilisation * 100, marker="o", color=GREY, label="portfolio utilisation")
    ax.set_title("Delinquency and utilisation by month (%)", loc="left", fontsize=11)
    ax.legend(fontsize=8, frameon=False); ax.spines[["top", "right"]].set_visible(False)
    ax.set_ylim(0, 35)

    # Roll-rate matrix
    ax = fig.add_subplot(gs[1, 3:6])
    order = ["0. current", "1. 1-2 months late", "2. 3+ months late"]
    names = ["Current", "1-2 late", "3+ late"]
    mat = np.zeros((3, 3))
    for _, row in r.iterrows():
        mat[order.index(row.from_bucket), order.index(row.to_bucket)] = row.roll_rate
    ax.imshow(mat, cmap="Reds", vmin=0, vmax=1, aspect="auto")
    for i in range(3):
        for j in range(3):
            ax.text(j, i, f"{mat[i, j]:.0%}", ha="center", va="center",
                    color="white" if mat[i, j] > 0.5 else DARK, fontsize=11)
    ax.set_xticks(range(3), names); ax.set_yticks(range(3), names)
    ax.set_xlabel("next month"); ax.set_ylabel("this month")
    ax.set_title("Roll-rate matrix, pooled Apr->Aug", loc="left", fontsize=11)

    # Monthly flow rates
    ax = fig.add_subplot(gs[2, 0:2])
    pairs = [p.split("->")[0][5:] + "-" + p.split("->")[1][5:] for p in rm.month_pair]
    labels = [f"{MONTHS[int(a) - 4]}\n>{MONTHS[int(c) - 4]}" for a, c in (x.split("-") for x in pairs)]
    ax.plot(labels, rm.current_to_late * 100, marker="o", color=ACCENT, label="current -> late")
    ax.plot(labels, rm.cure_rate * 100, marker="o", color=GREY, label="late -> current (cure)")
    ax.axvspan(3.5, 4.5, color="#F5F7FA"); ax.text(3.55, 33, "coding\nchange", fontsize=7.5, color="#52606D")
    ax.set_title("Monthly flow rates (%)", loc="left", fontsize=11)
    ax.legend(fontsize=8, frameon=False); ax.spines[["top", "right"]].set_visible(False)

    # Roll to default
    ax = fig.add_subplot(gs[2, 2:4])
    bl = ["Current", "1-2 late", "3+ late"]
    ax.bar(bl, b.default_rate * 100, color=[GREY, ACCENT, ACCENT])
    for i, (v, n) in enumerate(zip(b.default_rate * 100, b.accounts)):
        ax.text(i, v + 1.5, f"{v:.0f}%\n(n={n:,})", ha="center", fontsize=8)
    ax.set_ylim(0, 95)
    ax.set_title("Oct default rate by Sep bucket (%)", loc="left", fontsize=11)
    ax.spines[["top", "right"]].set_visible(False)

    # Segment
    ax = fig.add_subplot(gs[2, 4:6])
    seg = [x.split(". ", 1)[1] for x in s.segment]
    ax.barh(seg[::-1], (s.default_rate * 100)[::-1], color=GREY, label="Oct default rate")
    ax.scatter((s.dq1plus_rate * 100)[::-1], seg[::-1], color=ACCENT, zorder=3, label="Sep 1+ late")
    ax.set_title("By credit limit (NT$, %)", loc="left", fontsize=11)
    ax.legend(fontsize=7.5, frameon=False, loc="lower right"); ax.spines[["top", "right"]].set_visible(False)

    fig.text(0.06, 0.015, "Status code 1 ('1 month late') is used almost only in September, so 1- and 2-month "
             "delinquency are merged and the pooled roll rates use Apr->Aug. Source: Yeh (2009), UCI, CC BY 4.0.",
             fontsize=8, color="#52606D")
    FIG.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight"); plt.close(fig)
    return path


if __name__ == "__main__":
    con = build()
    k = kpis(con)
    for key, v in k.items():
        print(f"{key:32s} {v}")
    print(con.sql("SELECT * FROM dq_portfolio"))
    print("dashboard ->", dashboard(con, k))
