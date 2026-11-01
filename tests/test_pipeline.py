import json
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import model  # noqa: E402
import pipeline  # noqa: E402


@pytest.fixture(scope="session")
def con(tmp_path_factory):
    db = tmp_path_factory.mktemp("db") / "test.duckdb"
    c = pipeline.build(db)
    yield c
    c.close()


@pytest.fixture(scope="session")
def metrics(con):
    return model.run(con)


# ---------- data quality ----------
def test_blocking_dq_checks_pass(con):
    failed = con.execute("SELECT count(*) FROM dq_results WHERE severity='error' AND violations>0").fetchall()[0][0]
    assert failed == 0


def test_known_quirks_are_counted(con):
    dq = dict(con.execute("SELECT check_name, violations FROM dq_results WHERE severity='warn'").fetchall())
    assert dq["education_undocumented_code"] == 468
    assert dq["marriage_undocumented_code"] == 377


def test_pipeline_stops_on_bad_data(tmp_path, monkeypatch):
    bad = tmp_path / "bad.csv"
    lines = pipeline.RAW.read_text().splitlines()
    bad.write_text("\n".join(lines + [lines[1]]))  # duplicate a client
    monkeypatch.setattr(pipeline, "RAW", bad)
    with pytest.raises(pipeline.DataQualityError):
        pipeline.build(tmp_path / "bad.duckdb")


# ---------- staging & features ----------
def test_row_count_and_default_rate(con):
    n, rate = con.execute("SELECT count(*), avg(defaulted) FROM fct_client_features").fetchall()[0]
    assert n == 30000
    assert rate == pytest.approx(0.2212, abs=1e-4)


def test_education_codes_mapped(con):
    vals = {r[0] for r in con.execute("SELECT DISTINCT education FROM stg_clients").fetchall()}
    assert vals == {"graduate_school", "university", "high_school", "other_or_unknown"}


def test_months_late_count_bounds(con):
    lo, hi = con.execute("SELECT min(n_months_late_6m), max(n_months_late_6m) FROM fct_client_features").fetchall()[0]
    assert lo == 0 and hi <= 6


def test_max_late_ge_latest_late(con):
    bad = con.execute(
        "SELECT count(*) FROM fct_client_features WHERE max_months_late_6m < months_late_latest").fetchall()[0][0]
    assert bad == 0


def test_payment_ratio_bounded(con):
    lo, hi = con.execute(
        "SELECT min(payment_ratio_latest), max(payment_ratio_latest) FROM fct_client_features").fetchall()[0]
    assert lo >= 0 and hi <= 1


def test_marts_reconcile_to_total(con):
    for mart in pipeline.MARTS:
        n, d = con.execute(f"SELECT sum(clients), sum(defaults) FROM {mart}").fetchall()[0]
        assert (n, d) == (30000, 6636), mart


def test_demographics_not_in_model_features():
    for banned in ["sex", "age", "education", "marital_status"]:
        assert not any(banned in f for f in model.FEATURES)


# ---------- model ----------
def test_model_auc_reasonable(metrics):
    assert 0.74 <= metrics["auc_test"] <= 0.82


def test_no_large_overfit(metrics):
    assert metrics["auc_train"] - metrics["auc_test"] < 0.03


def test_deciles_rank_risk(metrics):
    assert metrics["top_decile_default_rate"] > 3 * metrics["bottom_decile_default_rate"]


def test_model_is_reproducible(con, metrics):
    again = model.run(con)
    assert again["auc_test"] == metrics["auc_test"]


def test_metrics_file_written(metrics):
    saved = json.loads((ROOT / "outputs" / "metrics.json").read_text())
    assert saved["auc_test"] == metrics["auc_test"]
