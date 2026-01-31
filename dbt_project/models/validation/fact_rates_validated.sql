{{
  config(
    materialized='incremental',
    unique_key=['rate_date', 'target_currency', 'base_currency'],
    incremental_strategy='merge',
    tags=['final', 'validated', 'hot-tier-source'],
    on_schema_change='fail'
  )
}}

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
    -- Get most recent extraction per day from Frankfurter (Primary source)
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY target_currency, rate_date
            ORDER BY extraction_timestamp DESC
        ) AS rn
    FROM {{ ref('stg_frankfurter') }}
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

-- ExchangeRate-API (Secondary source - daily mode only)
er_latest AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY target_currency, rate_date
            ORDER BY extraction_timestamp DESC
        ) AS rn
    FROM {{ ref('stg_exchangerate') }}
),

er_deduplicated AS (
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
    FROM er_latest
    WHERE rn = 1
),

-- CurrencyLayer (Tertiary source)
cl_latest AS (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY target_currency, rate_date
            ORDER BY extraction_timestamp DESC
        ) AS rn
    FROM {{ ref('stg_currencylayer') }}
),

cl_deduplicated AS (
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
    FROM cl_latest
    WHERE rn = 1
),

-- Get all unique date/currency combinations from all sources
all_dates_currencies AS (
    SELECT DISTINCT rate_date, target_currency, base_currency
    FROM frank_deduplicated
    UNION
    SELECT DISTINCT rate_date, target_currency, base_currency
    FROM er_deduplicated
    UNION
    SELECT DISTINCT rate_date, target_currency, base_currency
    FROM cl_deduplicated
),

-- COALESCE with source priority and lineage tracking
rates_with_priority AS (
    SELECT
        adc.rate_date,
        adc.target_currency,
        adc.base_currency,

        -- COALESCE: pick first non-NULL (Frankfurter → ExchangeRate → CurrencyLayer)
        {% if env_var("PIPELINE_MODE", "daily") == "backfill" %}
            -- Backfill mode: ExchangeRate-API unavailable (no historical data)
            COALESCE(f.exchange_rate, cl.exchange_rate) AS exchange_rate,
            COALESCE(f.inverse_rate, cl.inverse_rate) AS inverse_rate,
            CASE
                WHEN f.exchange_rate IS NOT NULL THEN 'frankfurter'
                WHEN cl.exchange_rate IS NOT NULL THEN 'currencylayer'
                ELSE NULL
            END AS actual_source_used,
            CASE
                WHEN f.exchange_rate IS NOT NULL THEN 'primary'
                WHEN cl.exchange_rate IS NOT NULL THEN 'tertiary'
                ELSE NULL
            END AS actual_source_tier,
            COALESCE(f.extraction_id, cl.extraction_id) AS extraction_id,
            COALESCE(f.extraction_timestamp, cl.extraction_timestamp) AS extraction_timestamp,
            COALESCE(f.currency_pair, cl.currency_pair) AS currency_pair
        {% else %}
            -- Daily mode: All sources available
            COALESCE(f.exchange_rate, er.exchange_rate, cl.exchange_rate) AS exchange_rate,
            COALESCE(f.inverse_rate, er.inverse_rate, cl.inverse_rate) AS inverse_rate,
            CASE
                WHEN f.exchange_rate IS NOT NULL THEN 'frankfurter'
                WHEN er.exchange_rate IS NOT NULL THEN 'exchangerate'
                WHEN cl.exchange_rate IS NOT NULL THEN 'currencylayer'
                ELSE NULL
            END AS actual_source_used,
            CASE
                WHEN f.exchange_rate IS NOT NULL THEN 'primary'
                WHEN er.exchange_rate IS NOT NULL THEN 'secondary'
                WHEN cl.exchange_rate IS NOT NULL THEN 'tertiary'
                ELSE NULL
            END AS actual_source_tier,
            COALESCE(f.extraction_id, er.extraction_id, cl.extraction_id) AS extraction_id,
            COALESCE(f.extraction_timestamp, er.extraction_timestamp, cl.extraction_timestamp) AS extraction_timestamp,
            COALESCE(f.currency_pair, er.currency_pair, cl.currency_pair) AS currency_pair
        {% endif %}

    FROM all_dates_currencies adc
    LEFT JOIN frank_deduplicated f
        ON adc.rate_date = f.rate_date
        AND adc.target_currency = f.target_currency
        AND adc.base_currency = f.base_currency
    LEFT JOIN er_deduplicated er
        ON adc.rate_date = er.rate_date
        AND adc.target_currency = er.target_currency
        AND adc.base_currency = er.base_currency
    LEFT JOIN cl_deduplicated cl
        ON adc.rate_date = cl.rate_date
        AND adc.target_currency = cl.target_currency
        AND adc.base_currency = cl.base_currency
    WHERE COALESCE(f.exchange_rate, er.exchange_rate, cl.exchange_rate) IS NOT NULL
),

-- Get consensus check results (only flagged rates)
anomalies AS (
    SELECT DISTINCT
        target_currency,
        rate_date,
        variance_pct,
        status,
        severity
    FROM {{ ref('consensus_check') }}
    WHERE status = 'FLAGGED'
)

SELECT
    -- Identifiers
    r.extraction_id,
    r.extraction_timestamp,
    r.rate_date,
    r.currency_pair,
    r.base_currency,
    r.target_currency,

    -- Rates
    r.exchange_rate,
    r.inverse_rate,

    -- Source metadata (lineage tracking)
    r.actual_source_used AS source,
    r.actual_source_tier AS source_tier,

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

FROM rates_with_priority r
LEFT JOIN anomalies a
    ON r.target_currency = a.target_currency
    AND r.rate_date = a.rate_date

-- CRITICAL: Only include validated rates (no anomalies)
WHERE validation_status = 'VALIDATED'

{% if is_incremental() %}
  -- Only process new/updated dates (with 7-day lookback for late-arriving data)
  AND r.rate_date >= (SELECT MAX(rate_date) FROM {{ this }}) - INTERVAL '7 days'
{% endif %}

ORDER BY r.rate_date DESC, r.target_currency
