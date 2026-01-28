
  
  create view "gold"."main_silver"."stg_exchangerate__dbt_tmp" as (
    

/*
Staging model for ExchangeRate-API rates.

Reads Bronze JSONL data from dlt and unpacks the flattened rates columns
into a normalized structure suitable for consensus checking.

Source: ExchangeRate-API (free tier)
Primary Source for USD-based exchange rates
*/

WITH bronze_data AS (
    -- Read from Silver Iceberg Table
    SELECT *
    FROM iceberg_scan('s3://silver-bucket/iceberg/exchangerate_rates/metadata/00007-259b8b7d-1ced-4edd-a210-7128e5d88cc9.metadata.json')
    WHERE source = 'exchangerate'
),

-- Extract all rates__* columns into rows using UNPIVOT
-- Using same currency list as Frankfurter for consistency
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
