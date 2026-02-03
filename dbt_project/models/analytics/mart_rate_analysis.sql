{{
  config(
    materialized='incremental',
    unique_key=['rate_date', 'base_currency', 'target_currency'],
    incremental_strategy='merge',
    tags=['gold', 'analysis']
  )
}}

WITH daily_rates AS (
    SELECT * FROM {{ ref('fact_rates_validated') }}
    {% if is_incremental() %}
      {% if env_var("PIPELINE_MODE", "daily") == "daily" %}
        -- Daily mode: Include 14-day lookback to ensure proper 7-day moving average calculation
        WHERE rate_date >= (SELECT MAX(rate_date) FROM {{ this }}) - INTERVAL '14 days'
      {% else %}
        -- Backfill mode: Process from execution date onwards (allows historical backfills)
        WHERE rate_date >= CAST('{{ env_var("EXECUTION_DATE", "1970-01-01") }}' AS DATE) - INTERVAL '14 days'
      {% endif %}
    {% endif %}
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

{% if is_incremental() %}
  {% if env_var("PIPELINE_MODE", "daily") == "daily" %}
    -- Daily mode: Only output new dates (filtering out the lookback window)
    WHERE rate_date >= (SELECT MAX(rate_date) FROM {{ this }})
  {% else %}
    -- Backfill mode: Output all dates from execution date onwards (allows out-of-order backfills)
    WHERE rate_date >= CAST('{{ env_var("EXECUTION_DATE", "1970-01-01") }}' AS DATE)
  {% endif %}
{% endif %}

ORDER BY base_currency, target_currency, rate_date DESC
