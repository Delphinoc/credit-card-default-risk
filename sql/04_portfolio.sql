-- 04_portfolio.sql
-- Portfolio monitoring layer: the view a retail-credit team would watch each month.
--   1. fct_account_month   one row per client per statement month (Apr-Sep 2005)
--   2. mart_portfolio_monthly   monthly portfolio KPIs (accounts, balances, delinquency rates)
--   3. mart_roll_rates     month-to-month movement between delinquency buckets
--   4. mart_roll_rates_monthly  key forward-roll and cure rates for each month pair
--   5. mart_bucket_to_default   September bucket -> October default ("roll to default")
--   6. mart_segment_delinquency September delinquency and October default by limit and utilisation band
--
-- Delinquency buckets come from the repayment status code:
--   status <= 0 (no use, paid in full, revolving) -> '0. current'
--   1 or 2 -> '1. 1-2 months late'      3+ -> '2. 3+ months late'
-- Why 1 and 2 are merged: status 1 ("1 month late") is used almost only in September
-- (3,688 accounts vs 34 across Apr-Aug), so the issuer appears to have coded early
-- delinquency differently before September. Merging keeps the buckets comparable across months.
-- For the same reason the consistent trend metric is "2+ months late" (status >= 2), and the pooled
-- roll-rate matrix uses Apr->Aug only; Aug->Sep is reported separately and flagged.
-- Balances are statement (bill) amounts in NT$; credit balances (negative bills) count as 0 outstanding.

CREATE OR REPLACE TABLE fct_account_month AS
WITH unpivoted AS (
    SELECT client_id, credit_limit, defaulted, 1 AS month_idx, '2005-04' AS statement_month,
           pay_status_apr AS pay_status, bill_apr AS bill, paid_apr AS paid FROM stg_clients
    UNION ALL SELECT client_id, credit_limit, defaulted, 2, '2005-05', pay_status_may, bill_may, paid_may FROM stg_clients
    UNION ALL SELECT client_id, credit_limit, defaulted, 3, '2005-06', pay_status_jun, bill_jun, paid_jun FROM stg_clients
    UNION ALL SELECT client_id, credit_limit, defaulted, 4, '2005-07', pay_status_jul, bill_jul, paid_jul FROM stg_clients
    UNION ALL SELECT client_id, credit_limit, defaulted, 5, '2005-08', pay_status_aug, bill_aug, paid_aug FROM stg_clients
    UNION ALL SELECT client_id, credit_limit, defaulted, 6, '2005-09', pay_status_sep, bill_sep, paid_sep FROM stg_clients
)
SELECT
    client_id, month_idx, statement_month, credit_limit, defaulted, pay_status, bill, paid,
    greatest(bill, 0)                                        AS outstanding,
    CASE WHEN pay_status <= 0 THEN '0. current'
         WHEN pay_status <= 2 THEN '1. 1-2 months late'
         ELSE                      '2. 3+ months late' END   AS dq_bucket,
    greatest(pay_status, 0)                                  AS months_late,
    (pay_status <> -2 OR bill <> 0)::INT                     AS is_active
FROM unpivoted;

-- 2. Monthly portfolio KPIs
CREATE OR REPLACE TABLE mart_portfolio_monthly AS
SELECT
    statement_month,
    count(*)                                                        AS accounts,
    sum(is_active)                                                  AS active_accounts,
    sum(outstanding)                                                AS outstanding_ntd,
    round(sum(outstanding) / sum(credit_limit), 4)                  AS portfolio_utilisation,
    round(avg((months_late >= 1)::INT), 4)                          AS dq1plus_rate_accounts,
    round(avg((months_late >= 2)::INT), 4)                          AS dq2plus_rate_accounts,
    round(sum(CASE WHEN months_late >= 1 THEN outstanding END) / sum(outstanding), 4) AS dq1plus_rate_balance,
    round(sum(CASE WHEN months_late >= 2 THEN outstanding END) / sum(outstanding), 4) AS dq2plus_rate_balance,
    sum(paid)                                                       AS payments_ntd
FROM fct_account_month
GROUP BY 1 ORDER BY 1;

-- 3. Roll-rate matrix, pooled over the four consistently coded month pairs (Apr->May ... Jul->Aug)
CREATE OR REPLACE TABLE fct_transitions AS
SELECT a.client_id, a.statement_month AS from_month, b.statement_month AS to_month,
       a.dq_bucket AS from_bucket, b.dq_bucket AS to_bucket, a.outstanding AS from_outstanding
FROM fct_account_month a
JOIN fct_account_month b ON a.client_id = b.client_id AND b.month_idx = a.month_idx + 1;

CREATE OR REPLACE TABLE mart_roll_rates AS
SELECT
    from_bucket, to_bucket,
    count(*)                                                                      AS transitions,
    round(count(*) / sum(count(*)) OVER (PARTITION BY from_bucket), 4)            AS roll_rate
FROM fct_transitions
WHERE to_month <= '2005-08'
GROUP BY 1, 2 ORDER BY 1, 2;

-- 4. Forward-roll and cure rates per month pair
CREATE OR REPLACE TABLE mart_roll_rates_monthly AS
SELECT
    from_month || '->' || to_month                                                AS month_pair,
    round(avg(CASE WHEN from_bucket = '0. current'      THEN (to_bucket > from_bucket)::INT END), 4) AS current_to_late,
    round(avg(CASE WHEN from_bucket = '1. 1-2 months late' THEN (to_bucket > from_bucket)::INT END), 4) AS late12_roll_forward,
    round(avg(CASE WHEN from_bucket <> '0. current'     THEN (to_bucket = '0. current')::INT END), 4) AS cure_rate,
    (to_month = '2005-09')                                                        AS coding_change_flag
FROM fct_transitions
GROUP BY from_month, to_month ORDER BY from_month;


-- 5. Roll to default: September bucket -> October default
CREATE OR REPLACE TABLE mart_bucket_to_default AS
SELECT dq_bucket AS sep_bucket,
       count(*) AS accounts, sum(outstanding) AS outstanding_ntd,
       sum(defaulted) AS defaults, round(avg(defaulted), 4) AS default_rate,
       round(sum(CASE WHEN defaulted = 1 THEN outstanding END) / sum(outstanding), 4) AS balance_default_rate
FROM fct_account_month WHERE statement_month = '2005-09'
GROUP BY 1 ORDER BY 1;

-- 6. Segment view (September): delinquency and next-month default by credit limit and utilisation
CREATE OR REPLACE TABLE mart_segment_delinquency AS
WITH sep AS (
    SELECT *, outstanding / credit_limit AS utilisation
    FROM fct_account_month WHERE statement_month = '2005-09'
)
SELECT 'credit_limit' AS dimension,
       CASE WHEN credit_limit <  50000 THEN 'a. <50k'
            WHEN credit_limit < 100000 THEN 'b. 50k-100k'
            WHEN credit_limit < 200000 THEN 'c. 100k-200k'
            WHEN credit_limit < 400000 THEN 'd. 200k-400k'
            ELSE                            'e. 400k+' END AS segment,
       count(*) AS accounts, round(avg((months_late >= 1)::INT), 4) AS dq1plus_rate,
       round(avg(defaulted), 4) AS default_rate
FROM sep GROUP BY 1, 2
UNION ALL
SELECT 'utilisation',
       CASE WHEN utilisation < 0.30 THEN 'a. <30%'
            WHEN utilisation < 0.50 THEN 'b. 30-50%'
            WHEN utilisation < 0.80 THEN 'c. 50-80%'
            WHEN utilisation < 1.00 THEN 'd. 80-100%'
            ELSE                         'e. 100%+' END,
       count(*), round(avg((months_late >= 1)::INT), 4), round(avg(defaulted), 4)
FROM sep GROUP BY 1, 2
ORDER BY 1, 2;

-- 7. Portfolio data-quality checks (error = blocking, warn = known quirk, reported)
CREATE OR REPLACE TABLE dq_portfolio AS
SELECT 'every_client_has_6_months' AS check_name, 'error' AS severity,
       (SELECT count(*) FROM (SELECT client_id FROM fct_account_month GROUP BY 1 HAVING count(*) <> 6)) AS violations
UNION ALL SELECT 'transitions_equal_5_per_client', 'error',
       abs((SELECT count(*) FROM fct_transitions) - 5 * (SELECT count(DISTINCT client_id) FROM fct_account_month))
UNION ALL SELECT 'roll_rate_rows_sum_to_1', 'error',
       (SELECT count(*) FROM (SELECT from_bucket FROM mart_roll_rates GROUP BY 1 HAVING abs(sum(roll_rate) - 1) > 0.001))
UNION ALL SELECT 'status_1_used_outside_september', 'warn',
       (SELECT count(*) FROM fct_account_month WHERE pay_status = 1 AND statement_month <> '2005-09');
