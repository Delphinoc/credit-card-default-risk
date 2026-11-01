-- 01_staging.sql
-- Load the raw UCI file, rename columns to readable month-based names and
-- tidy undocumented category codes. Months run Apr 2005 (oldest) to Sep 2005 (latest).
-- Repayment status codes (per dataset documentation and common usage):
--   -2 = no consumption, -1 = paid in full, 0 = revolving (minimum paid),
--    1..9 = payment delayed by N months.

CREATE OR REPLACE TABLE raw_clients AS
SELECT * FROM read_csv_auto('{raw_path}', header = true);

CREATE OR REPLACE TABLE stg_clients AS
SELECT
    ID                                   AS client_id,
    LIMIT_BAL                            AS credit_limit,
    -- Demographics are kept for descriptive reporting only; they are NOT used in the model.
    CASE SEX WHEN 1 THEN 'male' WHEN 2 THEN 'female' END AS sex,
    CASE EDUCATION
        WHEN 1 THEN 'graduate_school'
        WHEN 2 THEN 'university'
        WHEN 3 THEN 'high_school'
        ELSE 'other_or_unknown'           -- codes 0, 4, 5, 6 are undocumented / other
    END                                  AS education,
    CASE MARRIAGE
        WHEN 1 THEN 'married'
        WHEN 2 THEN 'single'
        ELSE 'other_or_unknown'           -- codes 0 and 3
    END                                  AS marital_status,
    AGE                                  AS age,

    PAY_0 AS pay_status_sep, PAY_2 AS pay_status_aug, PAY_3 AS pay_status_jul,
    PAY_4 AS pay_status_jun, PAY_5 AS pay_status_may, PAY_6 AS pay_status_apr,

    BILL_AMT1 AS bill_sep, BILL_AMT2 AS bill_aug, BILL_AMT3 AS bill_jul,
    BILL_AMT4 AS bill_jun, BILL_AMT5 AS bill_may, BILL_AMT6 AS bill_apr,

    PAY_AMT1 AS paid_sep, PAY_AMT2 AS paid_aug, PAY_AMT3 AS paid_jul,
    PAY_AMT4 AS paid_jun, PAY_AMT5 AS paid_may, PAY_AMT6 AS paid_apr,

    "default payment next month"         AS defaulted
FROM raw_clients;
