
  
    
    

    create  table
      "gold"."main_gold"."mart_rate_volatility__dbt_tmp"
  
    as (
      

/*
Currency Rate Volatility Analysis

Purpose: Risk assessment for FX exposure management
Business Value: Finance team identifies high-risk currencies for hedging decisions

Risk Levels:
- HIGH_RISK: >2% daily change OR >5% weekly change
- MEDIUM_RISK: >1% daily change OR >3% weekly change
- STABLE: Otherwise
*/

WITH daily_rates AS (
    SELECT
        rate_date,
        target_currency,
        exchange_rate,
        LAG(exchange_rate, 1) OVER (PARTITION BY target_currency ORDER BY rate_date) as prev_rate,
        LAG(exchange_rate, 7) OVER (PARTITION BY target_currency ORDER BY rate_date) as rate_7d_ago,
        LAG(exchange_rate, 30) OVER (PARTITION BY target_currency ORDER BY rate_date) as rate_30d_ago
    FROM "gold"."main_silver"."fact_rates_validated"
),

metrics AS (
    SELECT
        rate_date,
        target_currency,
        exchange_rate,

        -- Daily change %
        (exchange_rate - prev_rate) / NULLIF(prev_rate, 0) as daily_change_pct,

        -- 7-day change %
        (exchange_rate - rate_7d_ago) / NULLIF(rate_7d_ago, 0) as change_7d_pct,

        -- 30-day change %
        (exchange_rate - rate_30d_ago) / NULLIF(rate_30d_ago, 0) as change_30d_pct,

        -- 7-day rolling stddev
        STDDEV(exchange_rate) OVER (
            PARTITION BY target_currency
            ORDER BY rate_date
            ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
        ) as volatility_7d,

        -- 30-day rolling stddev
        STDDEV(exchange_rate) OVER (
            PARTITION BY target_currency
            ORDER BY rate_date
            ROWS BETWEEN 29 PRECEDING AND CURRENT ROW
        ) as volatility_30d

    FROM daily_rates
)

SELECT
    rate_date,
    target_currency,
    exchange_rate,
    daily_change_pct,
    change_7d_pct,
    change_30d_pct,
    volatility_7d,
    volatility_30d,

    -- Risk flag
    CASE
        WHEN ABS(daily_change_pct) > 0.02 OR ABS(change_7d_pct) > 0.05 THEN 'HIGH_RISK'
        WHEN ABS(daily_change_pct) > 0.01 OR ABS(change_7d_pct) > 0.03 THEN 'MEDIUM_RISK'
        ELSE 'STABLE'
    END as risk_level,

    CURRENT_TIMESTAMP as dbt_loaded_at

FROM metrics
WHERE rate_date >= CURRENT_DATE - INTERVAL '90 DAY'  -- Keep 90 days of history
ORDER BY rate_date DESC, target_currency
    );
  
  