

/*
Pre-computed Currency Conversion Matrix

Purpose: Provide direct conversion rates between top 10 currencies without manual calculation
Business Value: Payment processing - convert USD invoice to GBP directly

Example: To convert 100 USD to GBP, query WHERE from_currency='USD' AND to_currency='GBP'
*/

-- Pre-compute conversion matrix for top 10 currencies
WITH top_currencies AS (
    SELECT DISTINCT target_currency
    FROM "analytics"."main_validation"."fact_rates_validated"
    WHERE target_currency IN ('USD', 'EUR', 'GBP', 'JPY', 'AUD', 'CAD', 'CHF', 'CNY', 'HKD', 'SGD')
    AND rate_date = (SELECT MAX(rate_date) FROM "analytics"."main_validation"."fact_rates_validated")
),

latest_rates AS (
    SELECT
        rate_date,
        target_currency,
        exchange_rate as eur_rate,  -- EUR base (from fact table)
        inverse_rate as to_eur_rate
    FROM "analytics"."main_validation"."fact_rates_validated"
    WHERE rate_date = (SELECT MAX(rate_date) FROM "analytics"."main_validation"."fact_rates_validated")
)

-- Cartesian product for all pairs (cross-rate calculation)
SELECT
    f.rate_date,
    f.target_currency as from_currency,
    t.target_currency as to_currency,
    f.target_currency || '/' || t.target_currency as currency_pair,

    -- Cross rate calculation: (1 EUR = X FROM) / (1 EUR = Y TO) = X/Y
    (f.eur_rate / t.eur_rate) as exchange_rate,
    (t.eur_rate / f.eur_rate) as inverse_rate,

    CURRENT_TIMESTAMP as dbt_loaded_at
FROM latest_rates f
CROSS JOIN latest_rates t
WHERE f.target_currency != t.target_currency  -- Exclude same currency
  AND f.target_currency IN (SELECT target_currency FROM top_currencies)
  AND t.target_currency IN (SELECT target_currency FROM top_currencies)
ORDER BY from_currency, to_currency