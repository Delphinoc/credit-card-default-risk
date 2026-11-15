# Credit Card Default Risk Analysis

Which credit-card clients are most likely to miss next month's payment, and what should a card issuer do about it?

This project builds a **SQL (DuckDB) pipeline with data-quality checks**, an **interpretable logistic regression model**, and a **plain-English risk memo** for credit and collections teams. It uses 30,000 clients from the public UCI "Default of Credit Card Clients" dataset.

➡️ **Read the findings:** [`reports/risk_memo.md`](reports/risk_memo.md) (who will default) · [`reports/portfolio_memo.md`](reports/portfolio_memo.md) (how delinquency is moving)

## Headline results

- Clients **2+ months late** in September defaulted at **70%** next month (against 22% overall). They are 10% of clients but 33% of all defaults.
- The model reaches **AUC 0.77** on 9,000 held-out clients (Gini 0.53, KS 0.42). The riskiest 10% default at **68%** and the safest 10% at **6%**.
- The **top 20%** of risk scores capture **50%** of defaults, which supports a tiered collections strategy.
- **No demographics are used in the model.** Sex, age, education and marital status are left out as protected or sensitive attributes in credit decisions.

![Default rate by model risk decile](reports/figures/decile_default_rate.png)

## Portfolio monitoring extension

A second layer reshapes the data into **180,000 account-months** and tracks the KPIs a retail-credit team reviews each month: outstanding balances, utilisation, delinquency rates, **roll rates** between delinquency buckets, cure rates and roll-to-default.

- Outstanding balances grew **32%** (Apr→Sep) while the share of accounts 2+ months late rose from **10.3%** to a peak of **14.7%**.
- Each month **4.9%** of current accounts fell behind, and only **30%** of 1–2-month-late accounts cured.
- Accounts late in September were **23%** of the book but **52%** of October defaults.
- A **data-quality check caught a coding change**: status "1 month late" is used almost only in September (3,688 vs 34 accounts), so buckets were merged and roll rates pooled over consistently coded months.

![Portfolio dashboard](reports/figures/portfolio_dashboard.png)

## How it works

```
data/raw/default_of_credit_card_clients.csv
        │
sql/01_staging.sql        rename to readable month-based columns, map undocumented codes
sql/02_data_quality.sql   8 blocking checks (row count, unique IDs, nulls, ranges, binary target)
                          + 4 warning checks (undocumented codes, negative bills, over-limit balances)
sql/03_features.sql       behavioural features + 4 segment marts (status, utilisation, limit, late months)
        │
src/pipeline.py           runs the SQL, stops if any blocking check fails, exports CSVs
src/model.py              logistic regression, 70/30 stratified split, AUC/Gini/KS, risk deciles,
                          odds ratios with 95% CIs, comparison to a simple "2+ months late" rule
reports/risk_memo.md      findings, risk-tier actions, caveats
        │
sql/04_portfolio.sql      account-month panel, monthly KPIs, roll-rate matrix, roll-to-default, segment view
                          + 3 blocking checks and 1 warning check
src/portfolio.py          runs the portfolio layer, exports marts for Power BI / Tableau, draws the dashboard
reports/portfolio_memo.md trends, roll rates, recommendations, data-quality notes
tests/                    24 pytest tests (data quality, feature logic, mart reconciliation, model, portfolio checks)
```

## Run it

```bash
pip install -r requirements.txt
python src/pipeline.py      # build DuckDB database + data-quality report
python src/model.py         # train model, write metrics, charts and odds ratios
python src/portfolio.py     # portfolio KPIs, roll rates and dashboard
pytest -q                   # 24 tests
```

Outputs land in `outputs/` (metrics.json, odds_ratios.csv, test_deciles.csv, dq_results.csv, segment marts), `outputs/portfolio/` (portfolio marts) and `reports/figures/`.

## Data

Yeh, I. (2009). *Default of Credit Card Clients* [Dataset]. UCI Machine Learning Repository. https://doi.org/10.24432/C55S3H (licensed CC BY 4.0).
These are 30,000 clients of a Taiwanese card issuer, Apr–Sep 2005. The target is default in October 2005, and amounts are in NT$.

## Limitations

- The data comes from a single issuer in 2005, during a period of high card defaults. Patterns transfer better than absolute rates.
- Some repayment-status codes behave unexpectedly (for example, "paid in full" clients default slightly more than revolving clients), so each status is modelled as its own indicator.
- Odds ratios show associations, not causes, and the repayment-history features are correlated with each other.

## Tools

SQL (DuckDB) · Python (pandas, scikit-learn, statsmodels, matplotlib) · pytest
