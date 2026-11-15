import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import pipeline  # noqa: E402
import portfolio  # noqa: E402


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    c = pipeline.build(tmp_path_factory.mktemp("pdb") / "p.duckdb")
    portfolio.build(c)
    yield c
    c.close()


def q(con, sql):
    return con.execute(sql).fetchall()


def test_panel_has_six_months_per_client(con):
    assert q(con, "SELECT count(*) FROM fct_account_month")[0][0] == 180_000


def test_blocking_portfolio_checks_pass(con):
    assert q(con, "SELECT count(*) FROM dq_portfolio WHERE severity='error' AND violations>0")[0][0] == 0


def test_status_1_quirk_is_counted(con):
    v = dict(q(con, "SELECT check_name, violations FROM dq_portfolio WHERE severity='warn'"))
    assert v["status_1_used_outside_september"] == 34


def test_roll_rates_sum_to_one(con):
    for bucket, total in q(con, "SELECT from_bucket, sum(roll_rate) FROM mart_roll_rates GROUP BY 1"):
        assert abs(total - 1) < 1e-3, bucket


def test_pooled_roll_rates_exclude_coding_change(con):
    # 4 month pairs x 30,000 clients
    assert q(con, "SELECT sum(transitions) FROM mart_roll_rates")[0][0] == 120_000


def test_monthly_kpis_reconcile_to_panel(con):
    rows = q(con, "SELECT accounts, outstanding_ntd FROM mart_portfolio_monthly WHERE statement_month='2005-09'")
    panel = q(con, "SELECT sum(greatest(bill_sep,0)) FROM stg_clients")[0][0]
    assert rows[0][0] == 30_000 and rows[0][1] == panel


def test_bucket_to_default_reconciles(con):
    n, d = q(con, "SELECT sum(accounts), sum(defaults) FROM mart_bucket_to_default")[0]
    assert (n, d) == (30_000, 6_636)


def test_default_risk_rises_with_bucket(con):
    rates = [r[0] for r in q(con, "SELECT default_rate FROM mart_bucket_to_default ORDER BY sep_bucket")]
    assert rates == sorted(rates)


def test_dashboard_written(con, tmp_path):
    path = portfolio.dashboard(con, portfolio.kpis(con), tmp_path / "dash.png")
    assert path.exists() and path.stat().st_size > 50_000
