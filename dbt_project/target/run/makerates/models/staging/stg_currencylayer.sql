
  
  create view "analytics"."main_staging"."stg_currencylayer__dbt_tmp" as (
    

-- CurrencyLayer Staging
-- Base Currency is typically USD (Free Tier) or EUR (Paid)

WITH bronze_data AS (
    -- Read from Raw Iceberg Table
    SELECT *
    FROM iceberg_scan('s3://silver-bucket/iceberg/currencylayer_rates/metadata/00007-a32637fe-b979-4f3e-beb1-7d0bee54b5cc.metadata.json')
    WHERE source = 'currencylayer'
),

-- Extract all rates__* columns into rows using UNPIVOT
unnested_rates AS (
    UNPIVOT bronze_data
    ON COLUMNS('^rates__.*')
    INTO
        NAME target_currency
        VALUE exchange_rate
),

ranked_rates AS (
    SELECT 
        *,
        ROW_NUMBER() OVER (
            PARTITION BY base_currency, target_currency, rate_date 
            ORDER BY extraction_timestamp DESC
        ) as rn
    FROM unnested_rates
),

deduplicated AS (
    -- Deduplicate for each rate_date based on LATEST extraction_timestamp
    SELECT * FROM ranked_rates
    WHERE rn = 1
)

SELECT
    extraction_id,
    CAST(extraction_timestamp AS TIMESTAMP) AS extraction_timestamp,
    source,
    source_tier,
    base_currency,
    UPPER(REPLACE(target_currency, 'rates__', '')) AS target_currency,
    CAST(exchange_rate AS DOUBLE) AS exchange_rate,
    CAST(rate_date AS DATE) AS rate_date,
    CONCAT(base_currency, '/', UPPER(REPLACE(target_currency, 'rates__', ''))) AS currency_pair,
    1.0 / exchange_rate AS inverse_rate,  -- For reverse calculations
    CURRENT_TIMESTAMP AS dbt_loaded_at
FROM deduplicated
WHERE exchange_rate > 0
ORDER BY extraction_timestamp DESC, target_currency
  );
