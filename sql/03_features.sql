-- 03_features.sql
-- Behavioural features a card issuer would have at the end of September 2005.
-- Only repayment behaviour, balances and limits are used - no demographics.

CREATE OR REPLACE TABLE fct_client_features AS
WITH base AS (
    SELECT *,
        -- months-late values only (clip 'paid'/'no use' codes to 0)
        greatest(pay_status_sep, 0) AS late_sep, greatest(pay_status_aug, 0) AS late_aug,
        greatest(pay_status_jul, 0) AS late_jul, greatest(pay_status_jun, 0) AS late_jun,
        greatest(pay_status_may, 0) AS late_may, greatest(pay_status_apr, 0) AS late_apr
    FROM stg_clients
)
SELECT
    client_id,
    defaulted,
    credit_limit,
    -- repayment behaviour
    late_sep                                                         AS months_late_latest,
    greatest(late_sep, late_aug, late_jul, late_jun, late_may, late_apr) AS max_months_late_6m,
    (late_sep > 0)::INT + (late_aug > 0)::INT + (late_jul > 0)::INT
      + (late_jun > 0)::INT + (late_may > 0)::INT + (late_apr > 0)::INT AS n_months_late_6m,
    (pay_status_sep = -1)::INT                                       AS paid_in_full_latest,
    -- balances and utilisation
    bill_sep                                                         AS bill_latest,
    greatest(bill_sep, 0) / credit_limit                             AS utilisation_latest,
    (greatest(bill_sep,0) + greatest(bill_aug,0) + greatest(bill_jul,0) + greatest(bill_jun,0)
      + greatest(bill_may,0) + greatest(bill_apr,0)) / 6.0 / credit_limit AS utilisation_avg_6m,
    -- payment ratio: September payment against the August bill (payment for the prior statement)
    CASE WHEN bill_aug > 0 THEN least(paid_sep / bill_aug, 1.0) ELSE 1.0 END AS payment_ratio_latest,
    (paid_sep + paid_aug + paid_jul + paid_jun + paid_may + paid_apr) / 6.0  AS avg_payment_6m,
    -- descriptive only
    sex, education, marital_status, age
FROM base;

-- Segment marts used in the memo
CREATE OR REPLACE TABLE mart_default_by_latest_status AS
SELECT
    CASE
        WHEN pay_status_sep = -2 THEN 'a. no card use'
        WHEN pay_status_sep = -1 THEN 'b. paid in full'
        WHEN pay_status_sep =  0 THEN 'c. revolving (min. paid)'
        WHEN pay_status_sep =  1 THEN 'd. 1 month late'
        WHEN pay_status_sep =  2 THEN 'e. 2 months late'
        ELSE                          'f. 3+ months late'
    END AS latest_repayment_status,
    count(*)                    AS clients,
    sum(defaulted)              AS defaults,
    round(avg(defaulted), 4)    AS default_rate
FROM stg_clients GROUP BY 1 ORDER BY 1;

CREATE OR REPLACE TABLE mart_default_by_utilisation AS
SELECT
    CASE
        WHEN utilisation_latest < 0.10 THEN 'a. <10%'
        WHEN utilisation_latest < 0.30 THEN 'b. 10-30%'
        WHEN utilisation_latest < 0.50 THEN 'c. 30-50%'
        WHEN utilisation_latest < 0.80 THEN 'd. 50-80%'
        WHEN utilisation_latest < 1.00 THEN 'e. 80-100%'
        ELSE                                'f. 100%+'
    END AS utilisation_band,
    count(*) AS clients, sum(defaulted) AS defaults, round(avg(defaulted), 4) AS default_rate
FROM fct_client_features GROUP BY 1 ORDER BY 1;

CREATE OR REPLACE TABLE mart_default_by_limit AS
SELECT
    CASE
        WHEN credit_limit <  50000 THEN 'a. <50k'
        WHEN credit_limit < 100000 THEN 'b. 50k-100k'
        WHEN credit_limit < 200000 THEN 'c. 100k-200k'
        WHEN credit_limit < 400000 THEN 'd. 200k-400k'
        ELSE                            'e. 400k+'
    END AS credit_limit_band_ntd,
    count(*) AS clients, sum(defaulted) AS defaults, round(avg(defaulted), 4) AS default_rate
FROM fct_client_features GROUP BY 1 ORDER BY 1;

CREATE OR REPLACE TABLE mart_default_by_late_months AS
SELECT
    CASE WHEN n_months_late_6m >= 4 THEN '4-6' ELSE n_months_late_6m::VARCHAR END AS months_late_in_last_6,
    count(*) AS clients, sum(defaulted) AS defaults, round(avg(defaulted), 4) AS default_rate
FROM fct_client_features GROUP BY 1 ORDER BY 1;
