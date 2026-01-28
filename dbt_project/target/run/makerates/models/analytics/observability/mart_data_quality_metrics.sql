
  
    
    

    create  table
      "analytics"."main_analytics"."mart_data_quality_metrics__dbt_tmp"
  
    as (
      

/*
Pipeline Health & Data Quality Metrics

Purpose: SLA monitoring, detect stale data, track validation failures
Business Value: Operations team monitors pipeline health, gets alerts if data >2 days old

Health Status:
- HEALTHY: Fresh data (<2 days old), <5 flagged currencies, <10 warnings
- WARNING: Some warnings (>10 warnings)
- DEGRADED: Multiple failures (>5 flagged currencies)
- STALE: Data too old (>2 days since last rate)
*/

WITH latest_extraction AS (
    SELECT
        MAX(extraction_timestamp) as last_extraction,
        MAX(rate_date) as last_rate_date,
        COUNT(DISTINCT target_currency) as currency_count,
        COUNT(*) as total_records
    FROM "analytics"."main_validation"."fact_rates_validated"
),

validation_stats AS (
    SELECT
        COUNT(*) as validated_count,
        COUNT(*) FILTER (WHERE severity = 'OK') as ok_count,
        COUNT(*) FILTER (WHERE severity = 'WARNING') as warning_count
    FROM "analytics"."main_validation"."fact_rates_validated"
    WHERE rate_date = (SELECT MAX(rate_date) FROM "analytics"."main_validation"."fact_rates_validated")
),

consensus_stats AS (
    SELECT
        COUNT(*) as flagged_count,
        AVG(frank_dev) as avg_variance,
        MAX(frank_dev) as max_variance
    FROM "analytics"."main_validation"."consensus_check"
    WHERE status = 'FLAGGED'
      AND rate_date = (SELECT MAX(rate_date) FROM "analytics"."main_validation"."fact_rates_validated")
)

SELECT
    -- Freshness
    e.last_extraction,
    e.last_rate_date,
    DATEDIFF('hour', e.last_extraction, CURRENT_TIMESTAMP) as hours_since_extraction,
    DATEDIFF('day', e.last_rate_date, CURRENT_DATE) as days_since_rate,

    -- Volume
    e.currency_count,
    e.total_records,

    -- Validation
    v.validated_count,
    v.ok_count,
    v.warning_count,
    ROUND(v.ok_count::DOUBLE / NULLIF(v.validated_count, 0), 4) as ok_rate,

    -- Consensus
    COALESCE(c.flagged_count, 0) as flagged_count,
    c.avg_variance,
    c.max_variance,

    -- Health Check
    CASE
        WHEN DATEDIFF('day', e.last_rate_date, CURRENT_DATE) > 2 THEN 'STALE'
        WHEN COALESCE(c.flagged_count, 0) > 5 THEN 'DEGRADED'
        WHEN v.warning_count > 10 THEN 'WARNING'
        ELSE 'HEALTHY'
    END as pipeline_status,

    CURRENT_TIMESTAMP as dbt_loaded_at

FROM latest_extraction e
CROSS JOIN validation_stats v
LEFT JOIN consensus_stats c ON 1=1
    );
  
  