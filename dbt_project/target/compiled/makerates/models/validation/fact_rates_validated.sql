

/*
Fact Rates Validated: Final Validation Layer Output

This is the SINGLE SOURCE OF TRUTH for currency rates.
- Uses Frankfurter (ECB) as primary source
- Only includes rates that passed consensus validation
- Ready to sync to DynamoDB Hot tier for downstream services

Validation Rules:
- HTTP 200 response from API
- Rate > 0 (no nulls or zeros)
- Consensus check passed (variance <0.5% vs Open Exchange)
- Latest extraction per day (deduplication)
*/

WITH frank_latest AS (
    -- Get most recent extraction per day
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY target_currency, rate_date
            ORDER BY extraction_timestamp DESC
        ) AS rn
    FROM "analytics"."main_staging"."stg_frankfurter"
),

frank_deduplicated AS (
    SELECT
        extraction_id,
        extraction_timestamp,
        source,
        source_tier,
        base_currency,
        target_currency,
        exchange_rate,
        rate_date,
        currency_pair,
        inverse_rate
    FROM frank_latest
    WHERE rn = 1  -- Only latest extraction
),

-- Get consensus check results (only flagged rates)
anomalies AS (
    SELECT DISTINCT
        target_currency,
        rate_date,
        variance_pct,
        status,
        severity
    FROM "analytics"."main_validation"."consensus_check"
    WHERE status = 'FLAGGED'
)

SELECT
    -- Identifiers
    f.extraction_id,
    f.extraction_timestamp,
    f.rate_date,
    f.currency_pair,
    f.base_currency,
    f.target_currency,

    -- Rates
    f.exchange_rate,
    f.inverse_rate,

    -- Source metadata
    f.source,
    f.source_tier,

    -- Validation status
    CASE
        WHEN a.target_currency IS NOT NULL THEN 'FLAGGED'
        ELSE 'VALIDATED'
    END AS validation_status,

    COALESCE(a.severity, 'OK') AS severity,
    COALESCE(a.variance_pct, 0.0) AS consensus_variance,

    -- Metadata
    CURRENT_TIMESTAMP AS dbt_loaded_at,
    'fact_rates_validated' AS model_name

FROM frank_deduplicated f
LEFT JOIN anomalies a
    ON f.target_currency = a.target_currency
    AND f.rate_date = a.rate_date

-- CRITICAL: Only include validated rates (no anomalies)
WHERE validation_status = 'VALIDATED'

ORDER BY f.rate_date DESC, f.target_currency