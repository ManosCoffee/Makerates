
  
    
    

    create  table
      "analytics"."main_analytics"."mart_latest_rates__dbt_tmp"
  
    as (
      

WITH latest_rates AS (
    SELECT * FROM "analytics"."main_validation"."fact_rates_validated"
),

countries AS (
    SELECT * FROM "analytics"."main_analytics"."dim_countries"
)

SELECT
    r.rate_date,
    r.base_currency,
    r.target_currency,
    c.country_name,
    c.region,
    r.exchange_rate,
    r.inverse_rate,
    r.consensus_variance,
    r.validation_status,
    r.severity
FROM latest_rates r
LEFT JOIN countries c ON r.target_currency = c.currency_code
ORDER BY r.rate_date DESC, c.region, r.target_currency
    );
  
  