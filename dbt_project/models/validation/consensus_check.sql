{{
  config(
    materialized='incremental',
    unique_key=['rate_date', 'target_currency'],
    incremental_strategy='merge',
    tags=['validation', 'consensus']
  )
}}

/*
Consensus Check: Multi-Source Validation
Sources: ExchangeRate-API (Primary), Frankfurter (Secondary), CurrencyLayer (Tertiary/Failover)

Logic:
1. Normalize all rates to USD base.
2. Calculate Median Rate (Consensus).
3. Flag sources deviating > 0.5% from Median.
*/

WITH 
-- 1. Standardize Inputs
frank AS (
    SELECT rate_date, target_currency, exchange_rate as rate, 'frankfurter' as source
    FROM {{ ref('stg_frankfurter') }}
    WHERE base_currency = 'USD'
),

-- CurrencyLayer: Already USD base (free tier limitation)
cl_normalized AS (
    SELECT
        rate_date,
        target_currency,
        exchange_rate as rate,
        'currencylayer' as source
    FROM {{ ref('stg_currencylayer') }}
    WHERE base_currency = 'USD'
),

-- ExchangeRate-API: Already USD base (no conversion needed)
er_normalized AS (
    SELECT
        rate_date,
        target_currency,
        exchange_rate as rate,
        'exchangerate' as source
    FROM {{ ref('stg_exchangerate') }}
    WHERE base_currency = 'USD'
),

-- 2. Union All Sources
all_rates AS (
    SELECT * FROM frank
    UNION ALL
    SELECT * FROM cl_normalized
    UNION ALL
    SELECT * FROM er_normalized
),

-- 3. Calculate Consensus (Median) per Date/Currency
stats AS (
    SELECT
        rate_date,
        target_currency,
        MEDIAN(rate) as consensus_rate,
        COUNT(*) as source_count,
        LISTagg(source || ':' || ROUND(rate, 4), ', ') as source_breakdown
    FROM all_rates
    GROUP BY 1, 2
)

SELECT
    s.rate_date,
    s.target_currency,
    concat('USD/', s.target_currency) as currency_pair,
    s.consensus_rate,
    s.source_count,
    s.source_breakdown,
    
    -- Check specific deviations (for flagging)
    -- We join back to source data to find who deviated
    f.rate as frank_rate,
    er.rate as exchangerate_rate,
    cl.rate as currencylayer_rate,
    
    -- deviations
    ABS(f.rate - s.consensus_rate) / s.consensus_rate as frank_dev,
    ABS(er.rate - s.consensus_rate) / s.consensus_rate as er_dev,
    ABS(cl.rate - s.consensus_rate) / s.consensus_rate as cl_dev,

    -- variance_pct = maximum deviation across all sources (for flagging)
    GREATEST(
        COALESCE(ABS(f.rate - s.consensus_rate) / s.consensus_rate, 0.0),
        COALESCE(ABS(er.rate - s.consensus_rate) / s.consensus_rate, 0.0),
        COALESCE(ABS(cl.rate - s.consensus_rate) / s.consensus_rate, 0.0)
    ) as variance_pct,
    
    CASE 
        WHEN ABS(f.rate - s.consensus_rate) / s.consensus_rate > 0.005 THEN 'FLAGGED'
        WHEN ABS(er.rate - s.consensus_rate) / s.consensus_rate > 0.005 THEN 'FLAGGED'
        WHEN ABS(cl.rate - s.consensus_rate) / s.consensus_rate > 0.005 THEN 'FLAGGED'
        ELSE 'OK'
    END as status,
    
    CASE 
        WHEN ABS(f.rate - s.consensus_rate) / s.consensus_rate > 0.005 THEN 'WARNING'
        WHEN ABS(er.rate - s.consensus_rate) / s.consensus_rate > 0.005 THEN 'WARNING'
        WHEN ABS(cl.rate - s.consensus_rate) / s.consensus_rate > 0.005 THEN 'WARNING'
        ELSE 'OK'
    END as severity,
    
    CURRENT_TIMESTAMP as dbt_loaded_at
    
FROM stats s
LEFT JOIN frank f ON s.rate_date = f.rate_date AND s.target_currency = f.target_currency
LEFT JOIN er_normalized er ON s.rate_date = er.rate_date AND s.target_currency = er.target_currency
LEFT JOIN cl_normalized cl ON s.rate_date = cl.rate_date AND s.target_currency = cl.target_currency
WHERE s.consensus_rate IS NOT NULL
  -- Only include FLAGGED rows (anomalies)
  AND (
      ABS(f.rate - s.consensus_rate) / s.consensus_rate > 0.005
      OR ABS(er.rate - s.consensus_rate) / s.consensus_rate > 0.005
      OR ABS(cl.rate - s.consensus_rate) / s.consensus_rate > 0.005
  )
  AND (
      s.rate_date = CAST('{{ env_var("EXECUTION_DATE", "1970-01-01") }}' AS DATE)
      OR '{{ env_var("PIPELINE_MODE", "daily") }}' = 'backfill'
  )

{% if is_incremental() %}
  -- Only process new/updated dates (with 7-day lookback for late-arriving data)
  AND s.rate_date >= (SELECT MAX(rate_date) FROM {{ this }}) - INTERVAL '7 days'
{% endif %}
