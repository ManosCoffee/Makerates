
  
    
    

    create  table
      "gold"."main_gold"."mart_monthly_summary__dbt_tmp"
  
    as (
      

/*
Monthly Currency Rate Summary

Purpose: Pre-aggregated monthly rates for financial reporting and board presentations
Business Value: Finance team gets monthly summaries for YoY comparisons, trend analysis

Aggregations included:
- Min/Max/Avg/Median rates per month
- Opening/Closing rates (first/last day of month)
- Volatility percentage (range/average)
- Standard deviation
*/

WITH monthly_data AS (
    SELECT
        DATE_TRUNC('month', rate_date) as month,
        YEAR(rate_date) as year,
        MONTH(rate_date) as month_num,
        target_currency,
        exchange_rate,
        rate_date
    FROM "gold"."main_silver"."fact_rates_validated"
    WHERE rate_date >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '24 MONTH')  -- 2 years of history
)

SELECT
    month,
    year,
    month_num,
    target_currency,

    -- Aggregations
    COUNT(*) as sample_count,
    MIN(exchange_rate) as min_rate,
    MAX(exchange_rate) as max_rate,
    AVG(exchange_rate) as avg_rate,
    MEDIAN(exchange_rate) as median_rate,
    STDDEV(exchange_rate) as stddev_rate,

    -- Volatility indicator (range as % of average)
    (MAX(exchange_rate) - MIN(exchange_rate)) / AVG(exchange_rate) as volatility_pct,

    -- First and last rate of month (opening/closing)
    (SELECT exchange_rate FROM monthly_data m2
     WHERE m2.month = m.month AND m2.target_currency = m.target_currency
     ORDER BY rate_date ASC LIMIT 1) as opening_rate,
    (SELECT exchange_rate FROM monthly_data m2
     WHERE m2.month = m.month AND m2.target_currency = m.target_currency
     ORDER BY rate_date DESC LIMIT 1) as closing_rate,

    CURRENT_TIMESTAMP as dbt_loaded_at

FROM monthly_data m
GROUP BY 1, 2, 3, 4
ORDER BY month DESC, target_currency
    );
  
  