"""Run the SQL pipeline: staging -> data-quality checks -> features and marts.

Usage:  python src/pipeline.py
Creates outputs/credit_risk.duckdb and CSV exports of the data-quality results and marts.
"""
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "default_of_credit_card_clients.csv"
SQL_DIR = ROOT / "sql"
OUT = ROOT / "outputs"
DB_PATH = OUT / "credit_risk.duckdb"

MARTS = [
    "mart_default_by_latest_status",
    "mart_default_by_utilisation",
    "mart_default_by_limit",
    "mart_default_by_late_months",
]


class DataQualityError(RuntimeError):
    pass


def run_sql(con: duckdb.DuckDBPyConnection, name: str) -> None:
    sql = (SQL_DIR / name).read_text().replace("{raw_path}", RAW.as_posix())
    con.execute(sql)


def build(db_path: Path = DB_PATH) -> duckdb.DuckDBPyConnection:
    OUT.mkdir(exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    con = duckdb.connect(str(db_path))

    run_sql(con, "01_staging.sql")
    run_sql(con, "02_data_quality.sql")

    dq = con.sql("SELECT * FROM dq_results").df()
    failed = dq[(dq.severity == "error") & (dq.violations > 0)]
    if not failed.empty:
        raise DataQualityError(f"Blocking data-quality checks failed:\n{failed}")

    run_sql(con, "03_features.sql")

    dq.to_csv(OUT / "dq_results.csv", index=False)
    for m in MARTS:
        con.sql(f"SELECT * FROM {m}").df().to_csv(OUT / f"{m}.csv", index=False)
    return con


if __name__ == "__main__":
    con = build()
    print(con.sql("SELECT * FROM dq_results"))
    for m in MARTS:
        print(m)
        print(con.sql(f"SELECT * FROM {m}"))
