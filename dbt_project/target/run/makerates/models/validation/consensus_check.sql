
  
    
    

    create  table
      "analytics"."main_validation"."consensus_check__dbt_tmp"
  
    as (
      

/*
Consensus Check: Multi-Source Validation
Sources: ExchangeRate-API (Primary), Frankfurter (Secondary), CurrencyLayer (Tertiary/Failover)

Logic:
1. Normalize all rates to EUR base.
2. Calculate Median Rate (Consensus).
3. Flag sources deviating > 0.5% from Median.
*/

WITH 
-- 1. Standardize Inputs
frank AS (
    SELECT rate_date, target_currency, exchange_rate as rate, 'frankfurter' as source
    FROM "analytics"."main_staging"."stg_frankfurter"
    WHERE base_currency = 'EUR'
),

-- CurrencyLayer: Handle EUR and USD base
cl_raw AS (
    SELECT rate_date, base_currency, target_currency, exchange_rate
    FROM "analytics"."main_staging"."stg_currencylayer"
),

cl_eur_base AS (
    SELECT rate_date, target_currency, exchange_rate as rate
    FROM cl_raw
    WHERE base_currency = 'EUR'
),

cl_usd_base_pairs AS (
    SELECT rate_date, exchange_rate as usd_eur_rate
    FROM cl_raw
    WHERE base_currency = 'USD' AND target_currency = 'EUR'
),

cl_normalized AS (
    SELECT 
        r.rate_date, 
        r.target_currency, 
        r.exchange_rate / u.usd_eur_rate as rate,
        'currencylayer' as source
    FROM cl_raw r
    JOIN cl_usd_base_pairs u ON r.rate_date = u.rate_date
    WHERE r.base_currency = 'USD'
    
    UNION ALL
    
    SELECT *, 'currencylayer' as source FROM cl_eur_base
),

-- ExchangeRate-API is USD based, convert to EUR (Self-contained normalization)
er_raw AS (
    SELECT rate_date, base_currency, target_currency, exchange_rate
    FROM "analytics"."main_staging"."stg_exchangerate"
),

er_usd_eur AS (
    SELECT rate_date, exchange_rate as usd_to_eur
    FROM er_raw
    WHERE base_currency = 'USD' AND target_currency = 'EUR'
),

er_normalized AS (
    SELECT 
        e.rate_date, 
        e.target_currency, 
        e.exchange_rate / u.usd_to_eur as rate, 
        'exchangerate' as source
    FROM er_raw e
    JOIN er_usd_eur u ON e.rate_date = u.rate_date
    WHERE e.base_currency = 'USD'
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
    concat('EUR/', s.target_currency) as currency_pair,
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
    ABS(f.rate - s.consensus_rate) / s.consensus_rate as variance_pct, -- Alias for downstream consumption
    ABS(er.rate - s.consensus_rate) / s.consensus_rate as er_dev,
    ABS(cl.rate - s.consensus_rate) / s.consensus_rate as cl_dev,
    
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
  AND (
      s.rate_date = CAST('1970-01-01' AS DATE)
      OR 'daily' = 'backfill'
  )
    );
  
  