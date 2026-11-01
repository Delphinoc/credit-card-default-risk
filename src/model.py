"""Logistic regression default-risk model on behavioural features.

Usage:  python src/model.py   (runs the pipeline first if the database is missing)

Design choices
- Behavioural features only (repayment history, utilisation, limit, payments).
  Sex, age, education and marital status are excluded from the model: they are
  protected or sensitive attributes in credit decisions, and are reported only descriptively.
- Interpretable model (logistic regression) so each driver has an odds ratio a
  credit or collections team can read.
- 70/30 stratified split, fixed seed, all metrics reported on the held-out test set.
"""
import json
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.model_selection import train_test_split
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "outputs" / "credit_risk.duckdb"
FIG = ROOT / "reports" / "figures"
OUT = ROOT / "outputs"
SEED = 42

FEATURES = [
    "late_1m_latest",          # 1 month late in Sep
    "late_2m_plus_latest",     # 2+ months late in Sep
    "no_card_use_latest",      # status -2 in Sep
    "paid_in_full_latest",     # status -1 in Sep
    "n_months_late_6m",
    "max_months_late_6m",
    "log_credit_limit",
    "utilisation_latest",
    "utilisation_avg_6m",
    "payment_ratio_latest",
    "log_avg_payment_6m",
]


def load_features(con: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    df = con.sql(
        """
        SELECT f.*, s.pay_status_sep
        FROM fct_client_features f JOIN stg_clients s USING (client_id)
        """
    ).df()
    df["late_1m_latest"] = (df.pay_status_sep == 1).astype(int)
    df["late_2m_plus_latest"] = (df.pay_status_sep >= 2).astype(int)
    df["no_card_use_latest"] = (df.pay_status_sep == -2).astype(int)
    df["log_credit_limit"] = np.log(df.credit_limit)
    df["log_avg_payment_6m"] = np.log1p(df.avg_payment_6m)
    # cap extreme utilisation (negative/huge balances) so a few outliers don't dominate
    for c in ["utilisation_latest", "utilisation_avg_6m"]:
        df[c] = df[c].clip(0, 1.5)
    return df


def ks_statistic(y, p) -> float:
    fpr, tpr, _ = roc_curve(y, p)
    return float(np.max(tpr - fpr))


def decile_table(y, p) -> pd.DataFrame:
    d = pd.DataFrame({"y": np.asarray(y), "p": p})
    # decile 1 = highest predicted risk
    d["risk_decile"] = pd.qcut(d.p.rank(method="first", ascending=False), 10, labels=range(1, 11)).astype(int)
    t = d.groupby("risk_decile").agg(clients=("y", "size"), defaults=("y", "sum"), avg_pred=("p", "mean"))
    t["default_rate"] = t.defaults / t.clients
    t["cum_capture"] = t.defaults.cumsum() / t.defaults.sum()
    t["lift"] = t.default_rate / d.y.mean()
    return t.reset_index()


def run(con=None) -> dict:
    if con is None:
        if not DB_PATH.exists():
            from pipeline import build
            con = build()
        else:
            con = duckdb.connect(str(DB_PATH), read_only=True)
    FIG.mkdir(parents=True, exist_ok=True)

    df = load_features(con)
    X, y = df[FEATURES], df["defaulted"]
    X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, stratify=y, random_state=SEED)

    # 1) Predictive model (scaled, lightly regularised)
    clf = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, random_state=SEED))
    clf.fit(X_tr, y_tr)
    p_te = clf.predict_proba(X_te)[:, 1]
    p_tr = clf.predict_proba(X_tr)[:, 1]

    # 2) Interpretable odds ratios (unregularised statsmodels fit on the training set)
    logit = sm.Logit(y_tr, sm.add_constant(X_tr)).fit(disp=False)
    conf = logit.conf_int()
    odds = pd.DataFrame({
        "feature": logit.params.index,
        "coef": logit.params.values,
        "odds_ratio": np.exp(logit.params.values),
        "or_95ci_low": np.exp(conf[0].values),
        "or_95ci_high": np.exp(conf[1].values),
        "p_value": logit.pvalues.values,
    }).query("feature != 'const'")
    odds.to_csv(OUT / "odds_ratios.csv", index=False)

    # 3) Simple rule baseline: flag anyone 2+ months late in September
    rule = X_te["late_2m_plus_latest"].values
    rule_precision = float(y_te[rule == 1].mean())
    rule_recall = float(y_te[rule == 1].sum() / y_te.sum())

    deciles = decile_table(y_te, p_te)
    deciles.to_csv(OUT / "test_deciles.csv", index=False)
    top20 = deciles[deciles.risk_decile <= 2]

    metrics = {
        "n_train": int(len(y_tr)),
        "n_test": int(len(y_te)),
        "base_default_rate_test": round(float(y_te.mean()), 4),
        "auc_train": round(roc_auc_score(y_tr, p_tr), 4),
        "auc_test": round(roc_auc_score(y_te, p_te), 4),
        "gini_test": round(2 * roc_auc_score(y_te, p_te) - 1, 4),
        "ks_test": round(ks_statistic(y_te, p_te), 4),
        "top_decile_default_rate": round(float(deciles.loc[0, "default_rate"]), 4),
        "bottom_decile_default_rate": round(float(deciles.loc[9, "default_rate"]), 4),
        "top_20pct_capture": round(float(top20.defaults.sum() / deciles.defaults.sum()), 4),
        "top_20pct_default_rate": round(float(top20.defaults.sum() / top20.clients.sum()), 4),
        "rule_2m_late_flag_rate": round(float(rule.mean()), 4),
        "rule_2m_late_precision": round(rule_precision, 4),
        "rule_2m_late_recall": round(rule_recall, 4),
    }
    (OUT / "metrics.json").write_text(json.dumps(metrics, indent=2))

    _charts(con, deciles, odds, metrics)
    return metrics


def _charts(con, deciles, odds, metrics):
    grey, accent = "#9AA5B1", "#C8102E"

    # Default rate by latest repayment status
    s = con.sql("SELECT * FROM mart_default_by_latest_status").df()
    fig, ax = plt.subplots(figsize=(8, 4))
    labels = [x.split(". ", 1)[1] for x in s.latest_repayment_status]
    colors = [accent if "late" in l else grey for l in labels]
    ax.barh(labels[::-1], s.default_rate[::-1] * 100, color=colors[::-1])
    overall = con.execute("SELECT avg(defaulted) FROM stg_clients").fetchall()[0][0] * 100
    ax.axvline(overall, color="black", ls="--", lw=1)
    ax.text(overall + 1, -0.6, f"overall {overall:.1f}%", fontsize=8)
    for i, v in enumerate(s.default_rate[::-1] * 100):
        ax.text(v + 1, i, f"{v:.0f}%", va="center", fontsize=8)
    ax.set_xlabel("Default rate next month (%)")
    ax.set_title("Default rate by September repayment status")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIG / "default_rate_by_status.png", dpi=150); plt.close(fig)

    # Decile lift on test set
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(deciles.risk_decile, deciles.default_rate * 100,
           color=[accent if d <= 2 else grey for d in deciles.risk_decile])
    ax.axhline(metrics["base_default_rate_test"] * 100, color="black", ls="--", lw=1)
    ax.set_xticks(range(1, 11))
    ax.set_xlabel("Model risk decile (1 = highest risk)")
    ax.set_ylabel("Actual default rate (%)")
    ax.set_title(f"Held-out test set: top 20% of scores capture {metrics['top_20pct_capture']*100:.0f}% of defaults")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIG / "decile_default_rate.png", dpi=150); plt.close(fig)

    # Odds ratios
    o = odds.sort_values("odds_ratio")
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.errorbar(o.odds_ratio, o.feature, xerr=[o.odds_ratio - o.or_95ci_low, o.or_95ci_high - o.odds_ratio],
                fmt="o", color=accent, ecolor=grey, capsize=3)
    ax.axvline(1, color="black", lw=1)
    ax.set_xscale("log")
    ax.set_xlabel("Odds ratio (log scale, 95% CI)")
    ax.set_title("Drivers of default (logistic regression, training set)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(FIG / "odds_ratios.png", dpi=150); plt.close(fig)


if __name__ == "__main__":
    m = run()
    print(json.dumps(m, indent=2))
    print(pd.read_csv(OUT / "odds_ratios.csv").round(3).to_string(index=False))
    print(pd.read_csv(OUT / "test_deciles.csv").round(3).to_string(index=False))
