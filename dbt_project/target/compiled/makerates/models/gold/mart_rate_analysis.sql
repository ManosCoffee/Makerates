

WITH daily_rates AS (
    SELECT * FROM "gold"."main_silver"."fact_rates_validated"
)

SELECT
    rate_date,
    base_currency,
    target_currency,
    exchange_rate,
    -- Calculate 7-day Moving Average
    AVG(exchange_rate) OVER (
        PARTITION BY base_currency, target_currency 
        ORDER BY rate_date 
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ) as ma_7_day,
    -- Calculate Daily Volatility (Change from previous day)
    exchange_rate - LAG(exchange_rate) OVER (
        PARTITION BY base_currency, target_currency 
        ORDER BY rate_date
    ) as daily_change
FROM daily_rates
ORDER BY base_currency, target_currency, rate_date DESC