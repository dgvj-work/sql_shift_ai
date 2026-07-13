-- ML / DS feature engineering SQL (Vertica legacy)
-- Migrates to Snowflake / dbt feature mart for model training

CREATE LOCAL TEMP TABLE tmp_user_events ON COMMIT PRESERVE ROWS AS
SELECT
    user_id,
    event_ts,
    event_type,
    ZEROIFNULL(event_value) AS event_value
FROM staging.product_events
WHERE event_ts >= CURRENT_DATE - 90;

WITH user_agg AS (
    SELECT
        user_id,
        COUNT(*) AS event_count_90d,
        COUNT(DISTINCT event_type) AS event_type_nunique,
        SUM(event_value) AS value_sum_90d,
        AVG(event_value) AS value_avg_90d,
        DATEDIFF('day', MAX(event_ts), CURRENT_DATE) AS days_since_last_event
    FROM tmp_user_events
    GROUP BY user_id
),
labels AS (
    SELECT
        user_id,
        CASE WHEN ZEROIFNULL(churned_flag) = 1 THEN 1 ELSE 0 END AS churn_label
    FROM ml.churn_labels
    WHERE label_date = CURRENT_DATE - 1
)
SELECT
    a.user_id,
    a.event_count_90d,
    a.event_type_nunique,
    a.value_sum_90d,
    a.value_avg_90d,
    a.days_since_last_event,
    l.churn_label
FROM user_agg a
JOIN labels l ON a.user_id = l.user_id;
