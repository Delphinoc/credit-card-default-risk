-- 02_data_quality.sql
-- Each check returns one row: check name, severity, number of offending rows.
-- severity = 'error'  -> pipeline must stop if violations > 0
-- severity = 'warn'   -> known quirk of the data; counted and reported, not blocking

CREATE OR REPLACE TABLE dq_results AS
WITH s AS (SELECT * FROM stg_clients), r AS (SELECT * FROM raw_clients)
SELECT 'row_count_is_30000' AS check_name, 'error' AS severity,
       CASE WHEN (SELECT count(*) FROM s) = 30000 THEN 0 ELSE 1 END AS violations
UNION ALL SELECT 'client_id_unique', 'error',
       (SELECT count(*) - count(DISTINCT client_id) FROM s)
UNION ALL SELECT 'no_nulls_in_key_fields', 'error',
       (SELECT count(*) FROM s WHERE client_id IS NULL OR credit_limit IS NULL OR age IS NULL
            OR defaulted IS NULL OR pay_status_sep IS NULL OR bill_sep IS NULL OR paid_sep IS NULL)
UNION ALL SELECT 'default_flag_is_binary', 'error',
       (SELECT count(*) FROM s WHERE defaulted NOT IN (0, 1))
UNION ALL SELECT 'credit_limit_positive', 'error',
       (SELECT count(*) FROM s WHERE credit_limit <= 0)
UNION ALL SELECT 'age_between_18_and_100', 'error',
       (SELECT count(*) FROM s WHERE age NOT BETWEEN 18 AND 100)
UNION ALL SELECT 'pay_status_in_range_-2_to_9', 'error',
       (SELECT count(*) FROM s WHERE
            pay_status_sep NOT BETWEEN -2 AND 9 OR pay_status_aug NOT BETWEEN -2 AND 9 OR
            pay_status_jul NOT BETWEEN -2 AND 9 OR pay_status_jun NOT BETWEEN -2 AND 9 OR
            pay_status_may NOT BETWEEN -2 AND 9 OR pay_status_apr NOT BETWEEN -2 AND 9)
UNION ALL SELECT 'payments_non_negative', 'error',
       (SELECT count(*) FROM s WHERE least(paid_sep, paid_aug, paid_jul, paid_jun, paid_may, paid_apr) < 0)
-- Known quirks (warnings)
UNION ALL SELECT 'education_undocumented_code', 'warn',
       (SELECT count(*) FROM r WHERE EDUCATION NOT IN (1, 2, 3))
UNION ALL SELECT 'marriage_undocumented_code', 'warn',
       (SELECT count(*) FROM r WHERE MARRIAGE NOT IN (1, 2))
UNION ALL SELECT 'negative_bill_in_any_month', 'warn',
       (SELECT count(*) FROM s WHERE least(bill_sep, bill_aug, bill_jul, bill_jun, bill_may, bill_apr) < 0)
UNION ALL SELECT 'latest_bill_over_credit_limit', 'warn',
       (SELECT count(*) FROM s WHERE bill_sep > credit_limit);
